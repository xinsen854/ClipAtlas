"""Run current planner against a snapshot and render a review MP4, with no API calls."""
import asyncio
import json
import logging
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clipatlas.catalog.store import CatalogStore
from clipatlas.director.analyzer import DirectorAnalyzer
from clipatlas.director.service import DirectorService
from clipatlas.director.store import DirectorCacheStore
from clipatlas.exports.jianying import PyJianYingDraftBackend
from clipatlas.exports.models import JianyingExportSettings
from clipatlas.exports.service import TimelineExportService
from clipatlas.retrieval.local_rough_cut import LocalRoughCutSearch
from clipatlas.roughcut.planner import RoughCutPlanner
from clipatlas.roughcut.store import RoughCutStore
from clipatlas.rules.store import ProjectRuleStore
from clipatlas.speech.models import NarrationTrack
from clipatlas.speech.store import NarrationStore

DATA = Path('D:/ClipAtlas/data')
OUT = ROOT / 'scratch_ref' / ('real_video_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
FFMPEG = Path('D:/ClipAtlas/_internal/bin/ffmpeg.exe')
FFPROBE = FFMPEG.with_name('ffprobe.exe')


def local_path(uri):
    value = unquote(urlparse(uri).path)
    return Path(value.lstrip('/') if len(value) > 2 and value[2] == ':' else value)


class CachedAnalyzer(DirectorAnalyzer):
    async def analyze(self, *args, **kwargs):
        raise RuntimeError('Cache miss: real-video test forbids network analysis')


def run(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', cwd=OUT)
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:])
    return result.stdout


async def main():
    OUT.mkdir(parents=True)
    print('OUTPUT=' + str(OUT), flush=True)
    logging.basicConfig(filename=OUT / 'planner.log', level=logging.INFO, encoding='utf-8')
    for relative, name in [('library/library.sqlite3', 'library'),
                           ('narration/narration.sqlite3', 'narration'),
                           ('director/director.sqlite3', 'director'),
                           ('projects/project_rules.sqlite3', 'rules')]:
        with sqlite3.connect((DATA / relative).as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(OUT / (name + '.sqlite3')) as target:
                source.backup(target)
    narration = NarrationStore(OUT / 'narration.sqlite3')
    rules = ProjectRuleStore(OUT / 'rules.sqlite3')
    cache = DirectorCacheStore(OUT / 'director.sqlite3')
    analyzer = CachedAnalyzer(api_key='offline-test', base_url='http://127.0.0.1:1')
    with sqlite3.connect(OUT / 'narration.sqlite3') as db:
        tracks = [NarrationTrack.model_validate_json(r[0]) for r in db.execute(
            'SELECT payload_json FROM narration_tracks ORDER BY created_at DESC')]
    selected = None
    # Prefer the previously audited sample, then any aligned, cached real track.
    tracks.sort(key=lambda t: str(t.id) != '290c60ea-9315-4df2-8242-9f33e8817b70')
    for track in tracks:
        if str(track.timing_quality) not in {'aligned', 'unit_exact'} or not track.audio_uri:
            continue
        if not local_path(track.audio_uri).is_file():
            continue
        units = narration.list_units(track.id)
        script = '\n'.join(u.text for u in units)
        pack = (rules.get_by_revision(track.project_id, track.rule_pack_revision)
                if track.rule_pack_revision is not None else rules.get_active(track.project_id))
        rule_id = RoughCutPlanner._director_rule_identity(track.project_id, pack)
        empty = analyzer._empty_analysis(script, rule_id)
        if cache.get_by_key(empty.script_hash, empty.prompt_version, empty.rules_revision):
            selected = track
            break
    if selected is None:
        raise RuntimeError('No aligned real narration with matching Director cache')
    # Reproduce the narration's locked rule version in the isolated snapshot.
    rules.get_active = lambda project_id: pack
    catalog = CatalogStore(OUT / 'library.sqlite3')
    plans = RoughCutStore(OUT / 'plans.sqlite3')
    planner = RoughCutPlanner(narration_store=narration,
        search=LocalRoughCutSearch(search=None, catalog=catalog), store=plans,
        rule_store=rules, director=DirectorService(analyzer, cache))
    print(f'TRACK={selected.id} DURATION={selected.duration_ms} SCRIPT={script[:100]}', flush=True)
    plan = await planner.create_plan(selected.project_id, narration_track_id=selected.id, activate=False)
    (OUT / 'plan.json').write_text(plan.model_dump_json(indent=2), encoding='utf-8')
    (OUT / 'quality.json').write_text(plan.quality_report.model_dump_json(indent=2), encoding='utf-8')
    print(f'PLAN clips={len(plan.clips)} beats={len(plan.beats)}', flush=True)
    service = TimelineExportService(rough_cut_store=plans, narration_store=narration,
        export_root=OUT / 'exports', jianying_backend=PyJianYingDraftBackend())
    service.export_otio(plan.id)
    draft = service.export_jianying(plan.id, draft_name='单条实测', settings=JianyingExportSettings(
        draft_root=OUT / 'drafts', width=1080, height=1920))
    print('DRAFT=' + str(draft.output_path), flush=True)
    segments = []
    for i, clip in enumerate(plan.clips):
        duration = (clip.source_out_ms - clip.source_in_ms) / 1000
        target = OUT / f'clip_{i:03d}.mp4'
        run([FFMPEG, '-v', 'error', '-y', '-ss', clip.source_in_ms / 1000,
             '-i', local_path(clip.source_uri), '-t', duration, '-an', '-vf',
             'scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25',
             '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23', '-pix_fmt', 'yuv420p', target])
        segments.append(f"file '{target.name}'")
        print(f'RENDER {i+1}/{len(plan.clips)}', flush=True)
    (OUT / 'concat.txt').write_text('\n'.join(segments), encoding='utf-8')
    def stamp(ms):
        return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
    (OUT / 'subtitles.srt').write_text('\n\n'.join(
        f'{i+1}\n{stamp(s.start_ms)} --> {stamp(s.end_ms)}\n{s.text}'
        for i,s in enumerate(plan.subtitles)), encoding='utf-8')
    video = OUT / 'review.mp4'
    run([FFMPEG, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', OUT/'concat.txt',
         '-i', local_path(selected.audio_uri), '-map', '0:v:0', '-map', '1:a:0',
         '-vf', "subtitles=subtitles.srt:force_style='FontName=Microsoft YaHei,FontSize=18,MarginV=30'",
         '-t', plan.total_duration_ms/1000, '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
         '-c:a', 'aac', '-movflags', '+faststart', video])
    probe = json.loads(run([FFPROBE, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', video]))
    (OUT / 'probe.json').write_text(json.dumps(probe, indent=2), encoding='utf-8')
    run([FFMPEG, '-v', 'error', '-i', video, '-f', 'null', '-'])
    report = plan.quality_report
    summary = dict(output=str(video), draft=str(draft.output_path), duration_ms=plan.total_duration_ms,
        clips=len(plan.clips), videos=len({c.video_id for c in plan.clips}),
        director_counts={x:sum(c.director_fit==x for c in plan.clips) for x in ['DIRECT','SUPPORT','UNKNOWN','REJECT',None]},
        auto_direct=report.auto_direct_duration_ratio, s_direct=report.auto_s_direct_duration_ratio,
        coverage=report.timeline_coverage, repeats_ms=report.repeated_source_ms,
        lost_anchors=sum(c.evidence_retained is False for c in plan.clips),
        schedule=report.schedule_counts, network_calls=0)
    (OUT/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
