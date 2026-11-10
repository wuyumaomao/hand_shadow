# 手影数据集生成器

这是一个使用 Blender 生成手部和手影数据集的本地工具，支持单手或双手、手指弯曲、手部移动和旋转、Camera.001 相机控制、日光控制、网页预览，以及按规则批量生成输入输出图片对。

## 1. 环境要求

请先安装：

- Python 3.10 或更高版本
- Blender 4.x（本项目使用 Blender 4.4.3 验证）
- Pillow

安装 Pillow：

```powershell
python -m pip install -r requirements.txt
```

不需要单独安装 `bpy`。包含 `bpy` 的脚本会由 Blender 自带的 Python 执行。

## 2. 下载项目

```powershell
git clone <你的GitHub仓库地址>
cd scene_api
```

项目中的 `scenes/` 目录已经包含基础 Blender 场景：

```text
scenes/single_hand.blend
scenes/multi_hand.blend
```

这两个文件必须保留，因为手部模型、骨架、相机和光源都在其中。

## 3. 启动网页配置工具

在 PowerShell 中设置 Blender 路径。下面的路径需要改成你电脑上的实际路径：

```powershell
$ProjectDir = (Get-Location).Path
$PythonExe = "python"
$BlenderExe = "C:\Path\To\blender.exe"

& "$ProjectDir\start_web.ps1" `
  -PythonExe $PythonExe `
  -BlenderExe $BlenderExe
```

如果 `python` 已加入系统 PATH，可以直接使用；否则把 `$PythonExe` 改成 Python 可执行文件的完整路径。

启动后打开：

```text
http://127.0.0.1:8765
```

网页操作顺序：选择单手或双手，调整手部、相机和日光参数，查看预览，点击“确认基础场景”，再选择规则和数量并点击“生成输入输出对”。

网页服务运行期间请保留启动它的 PowerShell 窗口，按 `Ctrl+C` 可以停止服务。

## 4. 直接使用 JSON 渲染

不使用网页时，可以编辑 `configs/` 中的 JSON 文件。

配置基础场景：

```powershell
$ProjectDir = (Get-Location).Path
$PythonExe = "python"
$BlenderExe = "C:\Path\To\blender.exe"

& $PythonExe "$ProjectDir\configure_scene.py" `
  --config "$ProjectDir\configs\scene_config.json" `
  --blender $BlenderExe
```

生成数据集：

```powershell
& $PythonExe "$ProjectDir\generate_dataset.py" `
  --config "$ProjectDir\configs\generation_config.json" `
  --blender $BlenderExe
```

每次运行都会创建新的输出目录，不会覆盖已有结果：

```text
outputs/<任务编号>/
```

常见输出文件：

```text
images/              独立渲染图片
pairs/               左右拼接的输入输出图
pairs.json           配对索引和规则信息
plan.json            本次生成计划
render_manifest.json 实际渲染参数
```

`pairs/*.png` 是方便查看的拼接图；输入图和输出图分别位于 `images/` 中。

## 5. 当前规则

规则在 `pair_rules.py` 中统一定义：

| 规则 | 含义 |
|---|---|
| `count_preserve` | 输入和输出的弯曲手指数相同，但组合不同 |
| `shift_one` | 一根伸直手指循环向右移动一位 |
| `shift_two` | 两根伸直手指同时循环向右移动一位 |
| `lighting_l1` | 日光 X 旋转增加 30°，相机 X 位置增加 30 |
| `lighting_l2` | 日光 X 旋转减少 30°，相机 X 位置减少 30 |
| `stretch` | 日光 Y 设为 60°，相机 Y 位置设为 75 |

双手模式下，规则使用画面从左到右的长度10数组：左小指、左无名指、左中指、左食指、左拇指、右拇指、右食指、右中指、右无名指、右小指。最后一个位置向右移动时循环回第一个位置；渲染时再映射回每只手的骨骼顺序。

双手模式下，可以在生成配置中写：

```json
{
  "active_hands": ["left", "right"],
  "rules": [
    {"type": "count_preserve", "pair_count": 20}
  ],
  "seed": 42
}
```

规则会同时作用于两只活动手。`active_hands: ["left"]` 表示只改变左侧控制对象。

## 6. HTTP 后端

后端文件是 `api_server.py`，网页和其他程序都通过它提交任务。启动方式与网页相同：

```powershell
& "$ProjectDir\start_api.ps1" `
  -PythonExe $PythonExe `
  -BlenderExe $BlenderExe
```

常用接口：

```text
GET  /health
GET  /capabilities
POST /jobs
GET  /jobs/<任务ID>
POST /jobs/<任务ID>/cancel
GET  /jobs/<任务ID>/files/<文件名>
```

服务默认只监听本机 `127.0.0.1`，不会自动发布到公网。

## 7. 测试

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

需要进行 Blender 集成测试时：

```powershell
& $BlenderExe --background `
  --python-exit-code 1 `
  --python "$ProjectDir\tests\check_blender.py"
```

## 8. 发布注意事项

- 请把 `scenes/*.blend` 一起提交，否则别人没有可渲染的手部场景。
- 不要提交 `outputs/`、`__pycache__/`、日志和临时文件。
- 不要把 API key、个人路径或本地评测结果写入仓库。
- 确认手部模型和材质允许公开再分发。
