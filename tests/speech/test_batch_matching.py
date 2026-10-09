import pytest
from pathlib import Path

from clipatlas.speech.batches import BatchAudioFile, match_batch_audio, parse_batch_markdown


def files(*names):
    return [BatchAudioFile(name=name, size=100) for name in names]


def test_splits_numbered_md_and_matches_reordered_audio_without_using_upload_order():
    scripts = parse_batch_markdown("# 文案合集\n\n## 001 发布会\n第一条实际正文。\n\n## 002 越野\n第二条实际正文。")
    matches = match_batch_audio(scripts, files("002_越野.wav", "001_发布会.mp3"))
    assert [s.text for s in scripts] == ["第一条实际正文。", "第二条实际正文。"]
    assert [m.audio_index for m in matches] == [1, 0]
    assert all(m.reason == "编号匹配" for m in matches)


def test_first_paragraph_matching_is_explicit_and_ambiguous_prefix_is_not_assigned():
    scripts = parse_batch_markdown("这是一场汽车发布会的真实故事甲。\n\n正文甲\n---\n这是一场汽车发布会的真实故事乙。\n\n正文乙")
    matches = match_batch_audio(scripts, files("这是一场汽车发布会的真实故事.wav"))
    assert all(m.audio_index is None for m in matches)
    assert all("多条" in m.reason for m in matches)
    exact = match_batch_audio(scripts, files("这是一场汽车发布会的真实故事乙。.wav", "这是一场汽车发布会的真实故事甲。.wav"))
    assert [m.audio_index for m in exact] == [1, 0]


def test_duplicate_audio_and_conflicting_number_require_manual_review():
    scripts = parse_batch_markdown("## 001 发布会\n正文")
    matches = match_batch_audio(scripts, files("001.wav", "001.mp3"))
    assert matches[0].audio_index is None and matches[0].candidates == [0, 1]
    mismatch = match_batch_audio(scripts, files("002_001 发布会.wav"))
    assert mismatch[0].audio_index is None
    title_only = match_batch_audio(scripts, files("发布会.wav"))
    assert title_only[0].audio_index == 0 and title_only[0].reason == "标题匹配"


def test_fenced_headings_do_not_split_and_duplicate_codes_are_rejected():
    scripts = parse_batch_markdown("## 1 正文\n内容\n```md\n## 示例\n```\n## 2 正文\n第二条")
    assert len(scripts) == 2 and "## 示例" in scripts[0].text
    with pytest.raises(ValueError, match="重复"):
        parse_batch_markdown("## 001 标题\n正文\n## 1 标题\n另一条")
    with pytest.raises(ValueError, match="没有正文"):
        parse_batch_markdown("## 001 空条目")


def test_one_hundred_entries_match_by_code_and_larger_batch_is_rejected():
    markdown = "\n\n".join(f"## {i:03d} 标题\n第{i}条正文" for i in range(1, 101))
    scripts = parse_batch_markdown(markdown)
    matches = match_batch_audio(scripts, files(*(f"{i:03d}.wav" for i in range(100, 0, -1))))
    assert [m.audio_index for m in matches] == list(range(99, -1, -1))
    with pytest.raises(ValueError, match="最多100"):
        parse_batch_markdown(markdown + "\n## 101 标题\n多出的一条")


def test_cover_title_and_voiceover_prefix_are_stripped_for_alignment():
    markdown = (
        "封面标题：长假跑长途，辅助驾驶怎么用最安心？\n"
        "口播内容：马上到国庆长假，很多朋友自驾长途出行。辅助驾驶大概率会用到。\n"
        "---\n"
        "封面标题：L2.5、L2.9？强制国标一出，全作废！\n"
        "口播内容：买车时听过L2.5、L2.9、L2+吗？听着一个比一个高级。"
    )
    scripts = parse_batch_markdown(markdown)
    assert len(scripts) == 2
    # 封面标题行不进正文，口播内容前缀被去掉
    assert scripts[0].text == "马上到国庆长假，很多朋友自驾长途出行。辅助驾驶大概率会用到。"
    assert scripts[1].text == "买车时听过L2.5、L2.9、L2+吗？听着一个比一个高级。"
    # 标题本身仍保留，用于界面展示和文件名匹配
    assert scripts[0].title.startswith("封面标题：长假跑长途")
    assert scripts[1].title.startswith("封面标题：L2.5、L2.9？")


def test_cover_title_with_numbered_entry_keeps_code_and_cleans_body():
    scripts = parse_batch_markdown(
        "46.封面标题：长假跑长途，辅助驾驶怎么用最安心？\n"
        "口播内容：马上到国庆长假。\n"
        "47.封面标题：别把辅助驾驶当自动驾驶\n"
        "口播内容：国庆自驾，很多人会开领航辅助。"
    )
    assert [s.code for s in scripts] == ["046", "047"]
    assert scripts[0].text == "马上到国庆长假。"
    assert scripts[1].text == "国庆自驾，很多人会开领航辅助。"
    # 46(1).mp3 文件名不含编号，走手选（不自动猜测）
    assert match_batch_audio(scripts, files("46(1).mp3", "47(1)(1).mp3"))[0].audio_index is None


def test_user_three_numbered_scripts_keep_third_inline_body_and_numeric_facts():
    text = (Path(__file__).resolve().parents[1]/'fixtures/batch-three-numbered.md').read_text(encoding='utf-8')
    scripts = parse_batch_markdown(text)
    assert len(scripts) == 3
    assert [s.code for s in scripts] == ['001','002','003']
    assert scripts[0].text.startswith('央视专访中，北京越野')
    assert '24.98万元' in scripts[0].text and '8.6万元' in scripts[0].text
    assert scripts[1].text.startswith('8月25日晚') and 'ADS 5.0 MAX' in scripts[1].text
    assert scripts[2].text.startswith('一场上市直播，三个审视维度')
    assert '第一道是性能' in scripts[2].text and '第三道是定位' in scripts[2].text
    assert scripts[2].text.endswith('本身就是对产品成色最直接的确认。')
    assert sum(len(s.text) for s in scripts) > 1800
    matches = match_batch_audio(scripts, files('003.wav','001.wav','002.wav'))
    assert [m.audio_index for m in matches] == [1,2,0]


@pytest.mark.parametrize('first,second',[
    ('1.','2.'), ('1、','2、'), ('1)','2)'), ('（1）','（2）'), ('【1】','【2】'),
    ('１．','２．'), ('1\\.','2\\.'), ('一、','二、'), ('（一）','（二）'),
    ('文案1：','文案2：'), ('文案一：','文案二：'), ('第1条：','第2条：'), ('第一篇：','第二篇：'),
])
def test_numbered_boundary_variants(first,second):
    scripts = parse_batch_markdown(f'{first} 标题甲\n甲正文。\n\n{second} 标题乙\n乙正文。')
    assert [s.code for s in scripts] == ['001','002']
    assert [s.text for s in scripts] == ['甲正文。','乙正文。']


def test_collection_heading_numbering_nested_lists_and_fences():
    text = '# 合集\n\n1. 第一篇\n正文\n  1. 内部列表\n  2. 内部列表\n```md\n3. 代码示例\n```\n2. 第二篇\n第2条正文。'
    scripts = parse_batch_markdown(text)
    assert [s.code for s in scripts] == ['001','002']
    assert '2. 内部列表' in scripts[0].text and '3. 代码示例' in scripts[0].text
    assert scripts[1].text == '第2条正文。'
    ordinary = '这是一篇文案。\n\n1. 大梁\n2. 差速锁\n24.98万元。\n8.6万元。'
    assert len(parse_batch_markdown(ordinary)) == 1


def test_inline_scripts_bold_headings_and_chinese_audio_number_matching():
    assert [s.text for s in parse_batch_markdown('1. 一句话正文。\n2. Another sentence.\nContinuation.')]==[
        '一句话正文。','Another sentence.\nContinuation.']
    scripts=parse_batch_markdown('**一、发布会**\n正文甲\n**二、试驾**\n正文乙')
    assert [s.code for s in scripts]==['001','002']
    assert [m.audio_index for m in match_batch_audio(scripts,files('第二条_试驾.wav','第一条_发布会.wav'))]==[1,0]
    assert match_batch_audio(scripts,files('发布会.wav'))[0].audio_index==0


def test_numbered_duplicates_and_batch_limit_are_checked():
    with pytest.raises(ValueError,match='重复'):
        parse_batch_markdown('1. 标题\n正文\n1. 另一标题\n正文')
    text='\n'.join(f'{i}. 标题\n第{i}条正文' for i in range(1,101))
    assert len(parse_batch_markdown(text))==100
    with pytest.raises(ValueError,match='最多100'):
        parse_batch_markdown(text+'\n101. 多出一条\n正文')


def test_extract_cover_title_variants() -> None:
    from clipatlas.speech.batches import extract_cover_title

    assert extract_cover_title("46.封面标题：长假跑长途，辅助驾驶怎么用最安心？") == "长假跑长途，辅助驾驶怎么用最安心？"
    assert extract_cover_title("封面标题：普通标题格式") == "普通标题格式"
    assert extract_cover_title("7.标题：别把辅助驾驶当自动驾驶") == "别把辅助驾驶当自动驾驶"
    assert extract_cover_title("国庆自驾很多人会开领航辅助") is None


def test_draft_name_prefers_cover_title_over_first_sentence() -> None:
    from clipatlas.exports.models import draft_name_from_cover, draft_name_from_script

    cover = "L2.5、L2.9？强制性国标来了"
    assert draft_name_from_cover(cover) == "L2.5、L2.9？强制性国标来了"
    # 无封面标题时回退口播第一句（保持原规则）
    assert draft_name_from_script("马上到国庆长假，很多朋友自驾长途出行") == "马上到国庆长假很多朋友自驾长途出行"


def test_clean_script_removes_numbered_cover_line() -> None:
    from clipatlas.speech.batches import clean_script_text

    cleaned = clean_script_text(
        "46.封面标题：长假跑长途，辅助驾驶怎么用最安心？\n口播内容：马上到国庆长假，很多朋友自驾长途出行"
    )
    assert "封面标题" not in cleaned
    assert cleaned.startswith("马上到国庆长假")


def test_extract_cover_title_wide_formats() -> None:
    from clipatlas.speech.batches import extract_cover_title

    # 显式标签变体
    assert extract_cover_title("文案标题：L2.5、L2.9？强制国标一出，全作废！") == "L2.5、L2.9？强制国标一出，全作废！"
    assert extract_cover_title("作品标题：国产越野第一次被权威审视") == "国产越野第一次被权威审视"
    # 无标签编号行（标题可带问号）
    assert extract_cover_title("1. 长假跑长途，辅助驾驶怎么用最安心？") == "长假跑长途，辅助驾驶怎么用最安心？"
    assert extract_cover_title("文案1：别把辅助驾驶当自动驾驶") == "别把辅助驾驶当自动驾驶"
    assert extract_cover_title("第1条：强标来了") == "强标来了"
    assert extract_cover_title("第一条 国产越野第一次被权威审视") == "国产越野第一次被权威审视"
    # 正文行不能误判为标题
    assert extract_cover_title("国庆自驾很多人会开领航辅助") is None
    assert extract_cover_title(
        "1. 马上到国庆长假，很多朋友自驾长途出行，辅助驾驶大概率会用到。作为天天跟智驾打交道的测试工程师给大家两条建议。"
    ) is None
    assert extract_cover_title("2、这个视频讲的是大梁和电池骨架的区别。") is None


def test_clean_script_body_prefixes_wide() -> None:
    from clipatlas.speech.batches import clean_script_text

    cleaned = clean_script_text("文案标题：国产越野第一次被权威审视\n口播文案：作为天天跟智驾打交道的测试工程师")
    assert "文案标题" not in cleaned
    assert cleaned.startswith("作为天天跟智驾")

def test_parse_splits_by_cover_title_lines() -> None:
    from clipatlas.speech.batches import parse_batch_markdown

    md = """封面标题： 长假跑长途，辅助驾驶怎么用最安心？
口播内容：“马上到国庆长假，很多朋友自驾长途出行。
封面标题： 别把辅助驾驶当自动驾驶，国庆出行两条红线
口播内容： 国庆自驾，很多人会开领航辅助。
封面标题： L2.5、L2.9？强制国标一出，全作废！
口播内容： 买车时听过 L2.5、L2.9、L2+ 吗？”
"""
    scripts = parse_batch_markdown(md)
    assert len(scripts) == 3
    assert scripts[0].text.startswith("“马上到国庆长假")
    assert scripts[1].text.startswith("国庆自驾")
    assert scripts[2].text.startswith("买车时听过")


def test_parse_splits_by_bracket_titles_and_strips_hashtags() -> None:
    from clipatlas.speech.batches import parse_batch_markdown

    md = """《44个月缩到12个月，提速近4倍的背后！》
口播：44个月，12个月。#华为乾崑200万用户的信赖之选#
《覆盖全品类全价位！华为乾崑200万成绩单》
口播：中国智能网联汽车产业正经历一场深刻的商业蜕变。
"""
    scripts = parse_batch_markdown(md)
    assert len(scripts) == 2
    assert "华为乾崑200万用户的信赖之选" not in scripts[0].text
    assert scripts[1].text.startswith("中国智能网联汽车产业")


def test_extract_cover_title_bracket_form() -> None:
    from clipatlas.speech.batches import extract_cover_title

    assert extract_cover_title("《覆盖全品类全价位！华为乾崑200万成绩单是车企蜕变的见证》") == "覆盖全品类全价位！华为乾崑200万成绩单是车企蜕变的见证"
    assert extract_cover_title("《从选配到刚需！单年研发超180亿》") == "从选配到刚需！单年研发超180亿"
