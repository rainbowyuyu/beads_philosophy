# 图片 → 豆号图纸

把图片缩成格网，将每格颜色匹配到自己的拼豆色卡，导出带豆号的图纸和购买/清点用量表。透明背景会变成空格，保留“这里不放豆子”的意思。

## 快速开始

在仓库根目录执行（Python 3.10+，依赖 `numpy`、`Pillow>=10.1`）：

请先按[根目录说明](../README.md)安装虚拟环境。下文的 `python` 指该环境的解释器：Windows 使用 `.\.venv\Scripts\python.exe`，macOS / Linux 使用 `.venv/bin/python`；没有激活环境时，请直接用对应路径替换命令中的 `python`。

```bash
python beads/examples/make_example.py
python beads/image_to_beads.py beads/examples/flower.png --width 32 --output output/flower
```

`flower.png` 是本仓库用简单几何绘制的原创演示图，可随代码再分发。它不使用视频中第三方角色的图片。

自己的图片与色卡：

```bash
python beads/image_to_beads.py my-picture.png --width 48 --palette my-palette.csv --output output/my-pattern
```

`--width` 是横向格数，默认按图片比例计算纵向格数；`--height` 可以固定纵向格数，但可能改变长宽比。每轴最多 256 格。`--alpha-threshold 0.35` 表示一格至少有 35% 的不透明覆盖才放豆子，调高可清理透明边缘。JPEG 没有透明通道，需要先自行去背，工具不会把白色误当成背景。

## 色卡与真正的豆号

自备 UTF-8 CSV，格式为：

```csv
code,name,hex
MY01,我的白色,#F8F4EB
MY02,我的粉色,#E9849C
```

`code` 原样写到图纸里。请把对应品牌的真实豆号及其 RGB 色卡填进去。品牌之间不可直接套用豆号；颜色名称不是制造商色号。

**仓库内 `palettes/demo.csv` 的 D01–D10 只是 DEMO 自定义编号，不对应 MARD、Perler、Hama 等任何品牌。** 配色取自原创示例，尚未用实物珠子测色，不能按它当成品牌采购单。

## 输出

| 文件 | 用途 |
| --- | --- |
| `numbered-chart.png` | 带行列坐标、豆号及用量的图片图纸 |
| `numbered-chart.svg` | 可无损放大、供浏览器打开打印的矢量图纸 |
| `pixel-preview.png` | 整体像素配色预览，空格保留透明 |
| `beads-grid.json` | 格数、原样色号、调色板、每格索引及计数；空格为 `null` |
| `color-counts.csv` | 每种已使用颜色的数量，可用表格软件打开 |

`codes[row][column]` 从左上角开始；不是厂家拼板定位系统。再次输出到同一个目录会更新以上同名结果。

若自定义豆号或名称以 `= + - @` 开头，CSV 会加上单引号作为文本前缀，避免表格软件把它当公式执行；JSON 与图纸始终保留原始编号和名称。

PNG 文字优先使用本机可用字体；没有中文字体时，使用 `--font /path/to/font.ttf` 指定。SVG 中的名字保持原文，由浏览器本机字体显示。过长的豆号会缩小，常用短豆号更适合实物图纸。

## 颜色与透明边界怎么处理

先对原图做面积降采样，再在 CIELAB D65 空间用 ΔE76 距离选择最近的色卡颜色。不做抖动，避免平滑照片产生大量零散色格。透明区域按预乘 alpha 求平均，透明像素中隐藏的 RGB 不会把边缘染成黑色。

这个流程优化的是图片与屏幕色卡间的数值距离。显示器、灯光、珠子批次、相机白平衡和打印色差会影响实物效果；正式制作前建议少量试拼。输入图按 sRGB 处理，工具不会自动转换嵌入的其他 ICC 色彩空间。

## 验证

```bash
python -m unittest discover -s beads/tests -v
```

测试覆盖透明格、透明边缘、精确豆数、色卡重复编号、几何长宽、CSV/JSON 一致性、SVG 特殊字符和 CIELAB 黑白基准。

本工具把影片中的“面积采样 → 色卡匹配 → 豆号图纸”步骤整理成独立接口，没有复制原片角色素材、私有文件路径或机器学习训练管线。
