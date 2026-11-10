# 从三角网格到打印路径

这个模块把三维模型切成真实的水平截面，生成教学用轮廓和稀疏填充路径，再按路径长度驱动喷头预览。它还会找出向下的悬垂面，给出从打印平台生长的柱状支撑候选。

它适合研究「模型是怎样变成一层层路径的」，以及在视频中演示这一过程。实际打印请把模型交给专业切片器，选择自己的打印机、喷嘴与材料配置。

## 运行示例

在仓库根目录、已安装根目录依赖的 Python 环境中执行。下文 `python` 指根 README 中的虚拟环境解释器：Windows 为 `.\.venv\Scripts\python.exe`，macOS / Linux 为 `.venv/bin/python`。

```bash
python printing/examples/make_demo.py printing/examples/t-overhang.stl
python printing/slice_and_support.py printing/examples/t-overhang.stl --output output/printing-demo
```

打开 `output/printing-demo/preview.html`。可以播放、拖动时间条、旋转模型、查看当前层的顶视图与支撑位置；无需启动服务器，也不依赖远程脚本。仓库也提供已生成的 [T 形示例预览](examples/demo-preview/preview.html)，下载后用浏览器打开即可。默认 1 mm 层高用于让教学预览看清层与路径，并不是针对某台打印机推荐的生产参数。

使用自己的 GLB（通常以米为单位、Y 轴向上）：

```bash
python printing/slice_and_support.py model.glb --units m --up-axis y --height-mm 60 --layer-height 0.5 --line-width 0.4 --infill-spacing 2 --output output/my-model
```

STL 常见约定是毫米、Z 轴向上；STL 本身没有可靠的单位元数据，必须核对原文件的单位。OBJ 也没有统一的单位。程序不会自动猜测模型大小；`--height-mm` 表示明确将模型缩放到指定高度。

输入必须是封闭、法向绕序一致、体积为正的三角网格。程序保留 GLB 场景中的实例变换，再统一坐标，令 XY 居中、最低点落在 Z=0 平台。开口或自交网格应先在建模软件中修复。程序检查封闭性与截面有效性，但不是完整的网格自交检测器。

## 输出内容

| 文件 | 内容 |
| --- | --- |
| `normalized-model.stl` | 统一到毫米、Z 向上、底面为 0 的模型 |
| `simulation.json` | 每层的真实截面轮廓、孔洞、路径、路径长度及支撑筛查记录 |
| `supports.stl` | 有支撑候选时生成的独立柱状支撑网格；没有候选时不生成 |
| `preview.html` | 自包含可交互的逐层路径与喷头预览 |

切片位置取每层中面 `slice_z_mm`，喷头/沉积显示位置取该层顶面 `print_z_mm`。最后一层可小于指定层高。轮廓先向内偏置半个线宽，再生成周界；填充在进一步内缩的截面内按隔层换向的直线裁剪得到。多连通截面和孔洞不会被包围盒填满。

## 支撑设计规则

1. 按表面离开构建竖直方向的倾角筛选向下的悬垂面，默认超过 45°；水平底面是 90°。接触平台的底面不需要支撑。
2. 在真实悬垂面的 XY 投影内按网格采样，然后发射竖直射线，找到具体三角面上的接触高度。
3. 只生成落在构建平台上的支撑。如果下方已有模型占据，记录 `model_below_contact` 并跳过；不生成穿过模型的整根柱子。
4. 在柱子中心及圆周 16 个点发射竖直射线，检查柱体是否会碰到已有模型。被筛掉的记录为 `sampled_pillar_collision`。
5. 柱顶与模型留出指定接触间隙，导出 16 边圆柱几何。默认采样间距 4 mm、半径 0.6 mm、接触间隙 0.25 mm。

这是一种可追踪的支撑候选生成方法。圆周有限射线检查可能漏掉很细小的几何碰撞；网格采样也可能漏掉窄小悬垂。它没有桥接分析、树状支撑、生长在模型上的支撑、界面层、稳定性与强度优化，不能据此断言模型已获得完整支撑。候选柱子作为独立闭合网格输出，没有与主体做布尔合并；这保留了后续在专业切片器中重新设计支撑的空间。

## 路径仿真的范围

这里的「仿真」是几何与运动路径的教学预览。喷头沿已生成路径按弧长移动；路径之间显示不挤出的直线空移，换层重新从该层首条路径开始。动画速度不等于真实打印用时。没有流体、熔融、热传导、收缩或设备动力学模拟；没有完整顶底实心层、回抽、加速度、流量补偿和材料校准。支撑柱随高度显示，不表示已经生成支撑的实际挤出路径。

不生成可上机 G-code，不连接打印机。专业制作建议从以下项目继续：

- [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer)：成熟的 FDM/mSLA 切片与支撑工具，AGPL-3.0。
- [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer)：桌面切片、参数与路径预览，AGPL-3.0。具体输入格式以所安装版本为准。
- [Kiri:Moto](https://github.com/GridSpace/grid-apps)：浏览器切片环境与嵌入 API，MIT。
- [GCode Preview](https://github.com/xyz-tools/gcode-preview)：已生成 G-code 的可视化库，MIT；它本身不是网格切片器。
- [Prusa：层高与外壁](https://help.prusa3d.com/article/layers-and-perimeters_1748)：理解层高、XY 线宽与打印设置的不同作用。

本目录没有复制上述项目的源码；链接是进一步学习与实际生产的入口。

## 测试

```bash
python -m unittest discover -s printing/tests -v
```

测试覆盖已知尺寸立方体的面积与层高、路径落在实心截面内、环形截面的孔洞、T 形悬垂的真实接触高度、下方已有模型时拒绝穿透支撑，以及带场景变换的 GLB 米/Y-up 转换。

依赖：`numpy`、`trimesh`、`shapely`、`rtree`、`networkx`（均包含在仓库根目录依赖中）。示例 T 形几何由本仓库程序原创生成，不依赖视频角色或第三方模型资产。
