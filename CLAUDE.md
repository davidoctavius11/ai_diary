# ai_diary 项目规范

## 项目目标
把孩子的日记和照片转成可对话的语料库

## 技术栈
- Python 3.10+ (venv虚拟环境)
- 照片分析：智谱API
- OCR：Tesseract
- 向量库：ChromaDB

## 文件夹结构
ai_diary/
├── data/
│   ├── diary/     # 日记扫描件
│   ├── photos/    # 日常照片
│   └── fusion/    # 融合输出
├── scripts/       # Python代码
└── venv/          # 虚拟环境

## 当前任务
需要开发三个模块：
1. photo_analyzer.py - 照片分析
2. diary_parser.py - 日记解析
3. fusion_engine.py - 融合引擎
