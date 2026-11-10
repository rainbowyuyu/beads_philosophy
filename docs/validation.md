# 验证记录

日期：2026-11-10。以下区分程序检查、实际生成文件、浏览器观察与尚未完成的实物检查。

## 本机环境

- Windows，Python 3.13.14，仓库独立虚拟环境。
- NumPy 2.5.4、Pillow 12.3.0、trimesh 4.12.2、SciPy 1.18.1、Shapely 2.2.0、Rtree 1.4.1、NetworkX 3.7。
- `requirements.txt` 是允许范围；上述版本是这次实际运行版本。

## 自动检查

在根 README 安装好依赖后，在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/test_all.py
```

macOS / Linux 使用 `.venv/bin/python scripts/test_all.py`。

| 模块 | 通过 | 检查内容 |
| --- | ---: | --- |
| beads | 7 | 色卡校验、比例、透明格与透明边缘、计数、SVG 转义、CSV 文本安全与原编号保留 |
| minecraft | 5 | 场景实例变换、表面与实心占据、开放网格拒绝、PBR 纹理颜色、NBT 坐标及跨 64 位索引读回 |
| printing | 7 | 真实切片面积、路径落点、孔洞、悬垂支撑、已有模型遮挡、输入参数、GLB 单位和轴转换 |
| quantum | 4 | 维恩峰值、谱辐亮度单位与已知值、斯特藩–玻尔兹曼积分、非法输入 |
| 合计 | **23** | 本机全部通过 |

仓库另配置 GitHub Actions，在 Windows 与 Ubuntu 的 Python 3.13 环境运行同一套检查。实际云端结果请看仓库 Actions，不能由本机通过代替。

## 四条入口实际运行

下面的 `python` 请替换为已安装依赖的虚拟环境解释器。

```bash
python beads/image_to_beads.py beads/examples/flower.png --width 32 --output outputs/flower
python minecraft/model_to_blocks.py minecraft/examples/demo-sprout.glb --out outputs/minecraft/sprout --max-axis 36 --solid
python printing/slice_and_support.py printing/examples/t-overhang.stl --output outputs/printing-demo
python quantum/blackbody.py --out outputs/quantum
```

实际结果：

- 花朵图纸为 32 × 32 格，281 颗豆子、5 种演示色号。已查看编号图纸与统计图例。
- 豆芽雕塑为 28 × 36 × 25 格的包围范围，实际占据 7,122 个方块。已查看正视图，并由测试独立读回投影文件的 NBT；未启动游戏。
- T 形打印示例有 26 层、134 条周界/填充路径、18 根平台支撑候选。已生成独立 STL、JSON 与自包含 HTML。
- 黑体图比较 3000、4500、6000 K，维恩峰值分别为约 0.966、0.644、0.483 μm。已实际查看 SVG，确认三条曲线共用纵轴，图中单位为 MW，CSV 单位为 W。

## 浏览器观察

用 Ego Lite 打开下载后的本地打印示例 HTML，实际操作了：

- 播放与暂停，观察进度由 0.45 增至 0.505、层数由第 12 层更新为第 14 层。
- 跳转到 90% 与终点，确认第 24 层和第 26 层的截面与路径显示。
- 拖拽三维画布旋转，查看平台、T 形主体、支撑与金色喷头。
- 切换支撑与模型线框显示。
- 390 CSS 像素宽度下查看上下排列的两幅画布，未出现水平溢出；这是桌面浏览器窄视口检查，未做真实手机测试。

以上确认教学预览可操作，不代表真实打印过程的物理验证。

## 外部资源

- 四个模组由官方 Modrinth 下载，完成 SHA-512、长度与 JAR 内依赖元数据检查。版本与证据见 [Minecraft 验证记录](../minecraft/validation.json)、[版本锁](../minecraft/mods.lock.json) 和 [依赖记录](../minecraft/jar-dependencies.json)。
- 量子资料的 9 个入口完成 HTTP 状态与页面标题/主题核对，见 [链接检查记录](source-link-check.json)。这项检查不等于逐页重读整本教材。

## 尚未验证的范围

没有启动 Minecraft 导入投影，也没有实际打印或测量支撑强度。颜色匹配取决于用户提供的色卡与显示/材料条件；演示色卡不对应某个品牌。几何路径预览不包含材料、温度、喷头动力学仿真。黑体曲线为公式演示，普朗克尺度不是已证实的时空最小单位。
