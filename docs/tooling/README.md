# 方案文档维护

`build_documents.py` 从架构方案 Markdown 和现有图像生成项目根目录上一层的两份中文 Word。脚本依赖 python-docx 和可用中文字体，文档构建依赖无需加入业务后端依赖。当前交付使用 Codex 捆绑文档运行时生成，并用捆绑 LibreOffice 渲染逐页核验。

`draw_diagrams.py` 生成三份可编辑 SVG；对应的 Mermaid 图源位于 diagrams 目录，便于在支持 Mermaid 的仓库或编辑器中维护。Word 使用同名 PNG，修改 SVG 后应先同步 PNG，再生成 Word。

生成后需要重新渲染并检查每一页，特别是链路图高度、表格换行、中文字体和页尾。渲染 PDF 与页面 PNG 属于检查中间文件，本次未作为正式交付物。
