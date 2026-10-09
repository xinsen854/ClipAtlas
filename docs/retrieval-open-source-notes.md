# 开源匹配方案调研

2026-09-06 核对以下官方仓库和文档；本次未安装新的模型、数据库或开源服务。

| 项目 | 官方能力 | 对 ClipAtlas 的适用部分 |
|---|---|---|
| [StoryToolkitAI](https://github.com/octimot/StoryToolkitAI) | 本地转写、场景索引、视频搜索、LLM 辅助选择和故事编辑；EDL/XML 导出与 DaVinci Resolve 集成 | 工作流最接近本项目，可借鉴“素材索引→语义搜索→故事编排”；并非直接适配剪映的成品替代方案 |
| [Sentence Transformers](https://github.com/huggingface/sentence-transformers/blob/main/examples/sentence_transformer/applications/retrieve_rerank/README.md) | Retrieve & Re-Rank：词法/向量召回，再对候选做 Cross-Encoder 重排 | 分离便宜召回和较贵精排；不能直接把文本 Cross-Encoder 当成视频理解模型 |
| [Qdrant](https://qdrant.tech/documentation/search/hybrid-queries/) | 多路查询，RRF/DBSF 融合及多阶段检索 | 使用 RRF 思路融合 ASR/OCR/Visual 排名；现有数据量不必为此更换 SQLite |
| [CLIP-as-service](https://github.com/jina-ai/clip-as-service/blob/main/README.md) | CLIP 图文编码及 /rank 图文匹配重排 | 图文召回/排序设计可借鉴；本次继续使用已有百炼视觉向量，不替换模型 |
| [WhisperX](https://github.com/m-bain/whisperX/blob/main/README.md) | ASR、词级时间和强制对齐 | 属于时间对齐能力，不能解决画面选择；引入还需验证中文、模型资源与硬件开销 |

StoryToolkitAI 覆盖较完整的影视素材工作流，其他项目分别解决检索、排序、存储或对齐问题。没有依据表明安装其中一个就能直接完成本项目的
“中文长文案 + 私有多视频素材 + 连续镜头编排 + 剪映导出”全流程。
需要保留文案表达目的、辅助配图与具体证据的区别、真实时间和成片节奏。

本次采用的方法是全文规划、分证据召回、RRF 和有限候选复核。
预期减少重复模型请求和无效候选检查；具体提速幅度需用户第三条真实运行验证，不能据此承诺倍数。
