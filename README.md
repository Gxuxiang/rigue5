# Rigify 控制器控制 UE5 小白人（Manny）

用 `rigue5.blend` 里自带的 Rigify 骨架去驱动 `SKM_Manny.FBX` 的小白人，四肢 IK/FK、
手指、躯干、脚部滚动都能用。**没有面部控制器**（Manny 没有面部骨骼，元骨架里的 92 根
面部骨骼已经删掉，绑定只剩身体 + 手指）。

## 文件

| 文件 | 说明 |
| --- | --- |
| `rigue5_rigified.blend` | **交付文件**：Rigify 绑定 + 已对齐的小白人 |
| `rigue5.blend` | 你的原始文件，未改动 |
| `bake_to_ue.py` | 把动作烘焙成 UE 骨骼关键帧、得到可导出文件的脚本 |
| `duplicate_character.py` | 一键复制出第二个独立角色（做双人对打/对话用） |
| `preview/` | 效果图（静止 / 动作 / 弯腰） |
| `_build/` | 重新生成这套绑定的脚本，`build_all.py` 一键跑完；`pose_helper.py` 是姿态识别源文件，`verify_pose_capture.py` 是 headless 测试 |

## 打开文件后先做一件事：允许运行脚本

控制器面板（IK/FK 滑块、IK Parent 下拉框等）来自文件里的 `rig_ui.py`。
如果打开时提示“脚本被禁用”，面板不会出现，而且 FK/IK 两套控制器会同时显示，
看起来就像“控制器跑到外面去了”。

* 打开文件时如果弹出提示，选 **允许执行 / Allow Execution**；
* 或者：*偏好设置 → 保存和加载 → 自动运行 Python 脚本* 打开，再重新打开文件；
* 临时办法：文本编辑器 → 打开 `rig_ui.py` → **Run Script**（每次打开都要跑一次）。

## 怎么用

1. 选中 `rig`，进入 **Pose Mode**。
2. 拖控制器：小白人实时跟着动。
3. 四肢默认 **IK**（`hand_ik.L/R`、`foot_ik.L/R`）；想用 FK，选中
   `upper_arm_parent.L`、`thigh_parent.L` 这类骨骼，在 N 面板 Item 里把
   `IK_FK` 拉到 1（此时到 *骨骼集合* 面板把 `Arm.L (FK)` 等集合点亮，就能看到 FK 控制器）。

## 已做的几处调整（都是为了“控制器别乱跑”）

1. **脊椎骨骼映射修正（关键）**：原来 UE 的 `spine_01…spine_05` 和 Rigify 的
   `DEF-spine…` 错开了一节，弯腰时误差会累积，手和手指的控制器能甩到网格外
   15 cm 以上。现在按关节 1:1 对应：
   `spine_01→DEF-spine.001`、`spine_02→.002`、`spine_03/.004→.003`、
   `spine_05→.004`、`neck_01/.neck_02→.005`、`head→.006`。
   实测控制器离网格的距离：静止 1 cm、弯腰 90° 约 2.7 cm、弯到极限 180° 约 4.5 cm
   （修正前同样姿势是 10–15 cm）。
2. **手臂 IK 跟着肩膀走**：`hand_ik.L/R` 的父级改成 `shoulder.L/R`。弯腰/弯脊椎时
   手臂和控制器跟着上身走；脚仍然踩在 `root` 上不动。
3. **UE 骨架隐藏**：`root` 只是变形用的骨架（骨骼朝向很怪），已在视口里隐藏，只留
   网格 + Rigify 控制器。要在视口里看它：大纲视图点它的“眼睛”图标。
4. **FK 控制器默认隐藏**：`Arm.* (FK)`、`Leg.* (FK)` 集合默认关闭。**注意**：如果
   你手动点亮了 FK 集合，但手臂还在 IK 模式（`IK_FK=0`），这些 FK 控制器会停在
   静止位置 —— 那不是“跑偏”，切到 FK（`IK_FK=1`）或把 FK 集合关掉即可。
5. **手部控制器在伸直时保持对齐**。默认 `IK_Stretch = 0`，双手 IK 控制器停在手臂的可达
   边界。打开手臂拉伸后，UE 的肘和腕仍跟随 Rigify 解算位置。手指总控沿第一节指骨显示。
6. **脖子和头跟着身体转**：`torso` 骨骼上的 `Neck Follow` / `Head Follow` 设为
   **1.0**（Rigify 默认是 0.5 / 0）。原来弯腰时头不跟着躯干走，会歪在脖子上；
   现在头会随躯干一起弯。想微调就在 N 面板 *Rig Main Properties* 里改这两个值。
7. **手指末端骨骼朝向修正**：手指最后一节原来用了 FBX 骨骼自带的方向（UE 那些
   骨骼的 tail 方向是乱的），导致指尖的 FK 控制器飘到手掌里。现在最后一节按前
   两个关节的方向延长，控制器落在指尖上（骨骼末端到网格距离 0.1–0.3 cm）。
8. **转脖子只动头、不动肩膀**：UE 的 `spine_05` 是脖子根，而小人的锁骨挂在它下面。
   现在 `spine_05` 跟着 Rigify 的脖子根骨 `DEF-spine.004` 走（脖子能正常弯），
   同时把 `clavicle_l/r` 的**位置**钉在 `DEF-shoulder.L/R` 上。实测转 `neck` 30°：
   锁骨/大臂/手位移 `0.0000 m`，头位移 0.111 m。
9. **头部骨骼支点对准小人的头关节**：元骨架的 `spine.005` 末端和 `spine.006`
   起点改到小人的 `head` 关节（z≈1.626，原来是 `neck_02` 的 1.578）。原来转脖子时
   头骨绕低了 5 cm 的点转，控制器会甩到脑袋外面（偏离 9.7 cm）；现在偏离 4.1 cm
   （静止时是 3.1 cm，基本贴着头）。
10. **脖子控制器正视可见**。缩小 `WGT-rig_neck` 圆环，将它上移到颈部并倾斜
    36°，正视图里也能看到完整轮廓，旋转支点仍在颈根。

## 结构

```
Manny (UE5)      root（UE 骨架，视口隐藏）、SKM_Manny（网格）
Rigify           rig（控制器骨架）、metarig（对齐好的元骨架，隐藏）
RTG_CORRECTIVES  146 个空物体：145 个把 Rigify 骨骼的旋转精确换算成 UE 骨骼的旋转，
                 1 个（RTG_root__root）把 rig:root 的位移/旋转传给 UE 骨架对象
WGTS_rig         132 个控制器形状（自动隐藏，别删）
```

原理：Rigify 的 `DEF-*` 骨骼通过 145 个隐藏空物体把「旋转增量」传给 UE 骨骼
（这 145 个只传旋转，不传位移，所以小白人自身骨长/比例完全保留）。另外 1 个
`RTG_root__root` 把 `rig:root` 的位移/旋转传给 UE 骨架对象，也就是根运动。
静止姿势与原始模型误差 < 0.00001 m，带动画时角度误差 < 0.4°。

场景已清理过：删掉了空的 `Collection`、FBX 导入遗留的 `SKM_Manny.001` 空物体、
88 个旧绑定留下的面部控制器形状、Viewer 图像、以及所有 0 用户数据块。

## 做两个角色（双人对打 / 对话）

**在面板里点一下就行**：选中角色的 `rig` → 3D 视图按 `N` → **Rigify** 标签 →
「角色工具」→ **复制当前角色**。

（这段 UI 存在文件的文本块 `character_tools.py` 里，跟 Rigify 面板一样需要允许脚本
运行。想改名字前缀 / 偏移量，点完按钮后按 `F9` 调。）

它会把当前角色整套复制：`rig` / `root` / 网格 / 全部 `RTG_` 空物体（146 个），把副本内部的
父子关系和约束重新指向副本自己，重命名成 `B_*`，放进 `B character` 集合并在 X 轴
错开 1.3 m。也可以命令行跑 `duplicate_character.py`，效果一样。

实测（两个角色各自独立）：

| 操作 | 原角色位移 | B 角色位移 |
| --- | --- | --- |
| 转动 A 的 `hand_ik` | 0.319 m | 0.0000 m |
| 转动 B 的 `hand_ik` | 0.0000 m | 0.319 m |

⚠️ **不要用「物体模式全选 → 复制」**：`root` 和 146 个 `RTG_` 空物体为了方便
看视口是**隐藏**的（本文件共隐藏 147 个对象），Blender 的全选选不到隐藏物体，
结果只复制了 `rig` + 网格 —— 副本的网格仍然绑在**原来**的 `root` 上，副本的 rig
没有任何东西可驱动，拖它当然不会动。按钮/脚本会先临时解除隐藏再整组复制。

Rigify 面板两个角色都能用（`rig_id` 相同，面板按当前激活对象工作）。

要点：

* **必须整组复制**（rig + root + 网格 + 空物体），只复制 rig 和网格的话约束还会
  指向原来那套空物体，第二个角色就不受自己控制。
* 两个角色各在自己的 `rig` 上 K 帧，互不干扰；导出时分别选中各自的
  `root` + 网格导出 FBX（或在同一 FBX 里一起导出，UE 会识别成两个骨骼网格）。
* 动画仍然是"在 `rig` 上摆姿势 → 烘焙/导出时采样到 `root`"，两个角色各烘焙各的。
* 如果是**不同模型**（不是同一个 Manny），不能复制，需要按同样流程重新对齐绑定：
  把 `_build/ue_map.py` 里的关节对应关系换成新模型的骨骼名，再跑 `build_all.py`。

## 根运动（Root Motion）

**两种摆法，位移和旋转都会进 FBX 的根节点：**

* 物体模式选中 `rig`，移动/旋转后给它的 `location` / `rotation` K 帧；
* 或者在 Pose 模式直接推/转脚下的 `root` 圆环（控制骨骼）。

实测 1:1 跟手，不形变（移动 1 m，角色就移动 1 m；转 45°，导出后根节点也转 45°）。
导出的 FBX 里，根节点（也就是 UE 的 `root` 骨骼；导入 Blender 时会被吸收成
armature 对象）带 `location` + `rotation` 动画，UE 导入后识别成根运动。骨盆骨只
保留相对根节点的动作，所以转向不会被拆成“根节点没转、骨盆骨在转”。

**不要移动网格或 `root` 骨架**，这也是"移一下角色就变得非常大还形变"的原因：

| 操作 | 结果 |
| --- | --- |
| 移动 `rig` | ✅ 1 m → 1 m，比例不变 |
| 移动 `SKM_Manny`（网格） | ❌ 它挂在 0.01 缩放的父级下：拖 1 单位只走 1 cm，还会滑出骨架 |
| 移动 `root`（UE 骨架） | ❌ 完全不动（骨盆被世界空间约束钉在 rig 上） |
| 缩放 `rig` ×1.5 | ❌ 角色直接放大 **100 倍**并变形 |
| 缩放 `root` ×1.5 | ❌ 放大 **150 倍** |

所以文件里已经把这些锁死了：`rig` 的**缩放**锁定，`root` 和网格的**位移/旋转/缩放**
全部锁定（N 面板里字段旁边的小锁）。以后想动角色，只用 `rig` 或 `rig` 的 `root`
控制，别去碰 UE 骨架和网格。

导出带根运动的动画：

1. 面板点**「导出 FBX（含根运动）」**（已经按 UE 需要的参数设好：烘焙动画、
   全部骨骼、不导出叶子骨）—— 先在「动作」菜单选好要导的动作，选个路径就导完了；
2. 或者手动：面板点「显示/隐藏 UE 骨架」→ 文件 → 导出 → FBX，**必须勾选烘焙动画**，
   否则导出的是静止姿势（`b.fbx` / `c.fbx` 就是这样，里面一帧动画都没有）；
3. 或者先跑 `bake_to_ue.py` 把动作烘到 `root` 骨骼上再导出（这个脚本只烘骨骼姿势，
   根运动请用方式 A；面板导出会把根节点的位移/旋转一起烘进 FBX）。

### 按动作导出（多段动画）

「角色工具」面板里有**「动作：…」菜单**，列出当前 rig 的所有 Action 和各自的
帧范围：

| 选择 | 行为 |
| --- | --- |
| 当前时间轴（默认） | 和以前一样，按场景帧范围导出当前显示的动作 |
| 某个 Action | 临时切到该动作、按**动作自己的帧范围**烘焙导出 |

导出完会自动把当前动作、动作槽位、场景帧范围和当前姿势还原，不会动你正在
编辑的东西。导出前会先把 `rig` 清到静止姿势，避免上一段动作里没有 K 帧的通道
残留（尤其是根运动的位移/旋转），所以每个 Action 都是独立的一段动画。所以一段动画一个
Action 时，直接选 Action 导出即可，不用每次去改时间轴的范围。

> 动作要建立在 `rig` 对象上（在 Action Editor 里给 `rig` 新建/指定动作）。
> 根运动的关键帧也在同一个 Action 里：物体模式 `rig` 的 `location`/`rotation`，
> 或 Pose 模式 `root` 控制骨骼的位移/旋转。

**根运动落在哪**。`rig` 的 `root` 骨骼（脚下圆环）通过辅助空物体 `RTG_root__root`
驱动 **UE 骨架对象的位置和旋转**。UE 骨架对象就是 UE 的 `root` 骨骼节点（导入
Blender 时被吸收成 armature 对象），所以导出后就是 UE 的根运动。`pelvis` 复制
`DEF-spine` 的旋转，但不含根旋转；髋部自身的移动（`torso` 控制前后/左右挪）通过
`RTG_pelvis__DEF-spine` 保留成 `pelvis` 骨骼的位移，不会被折进根节点。手脚 IK 骨
会另外烘焙各自的局部位移和旋转。以下是加入 IK 跟随前的根运动测试，与 UE 导出的
`root_anim.fbx` 对比。

| | 你的 `root_anim.fbx` | 本文件的导出 |
| --- | --- | --- |
| 骨骼数 | 160 | 160 |
| 无父级关节 | pelvis、ik_foot_root、ik_hand_root、interaction、center_of_mass | 完全相同 |
| 对象级动画通道 | 9（location / rotation / scale） | 9 |
| 位移曲线 | location.idx1：−2.00 → 0.00 | location.idx1：0.00 → 2.00 |
| 骨骼位移 | 无 | 无 |

也就是说两边的动画结构完全一致：都是“根节点平移/旋转 + 骨骼旋转”，UE 导入后能识别成根运动。
（方向符号不同只是因为我测试时往 +Y 走、你往 −Y 走，Manny 面向 −Y，正常走路请朝 −Y。）

## 导出回 UE5

**方式 A（推荐）**：选中 `rig` → N 面板 **Rigify → 角色工具** →「动作」菜单里选
要导出的 Action（默认「当前时间轴」）→ 点 **导出 FBX（含根运动）**。参数已经按
UE 需要设好，选个路径就导完了。

导出时，`ik_foot_l/r` 和 `ik_hand_l/r` 跟随对应的脚和手，`ik_hand_gun` 跟随右手。
如果 UE 的 Skeleton Tree 启用了 Translation Retargeting，这些 IK 骨应使用 `Animation`，
以读取 FBX 里的位移轨道。

**方式 B**：选中 `root` + `SKM_Manny` → 文件 → 导出 → FBX，
勾选 **烘焙动画 / Bake Animation**。约束会在烘焙时被采样成 UE 骨骼的关键帧，
骨架名、层级、蒙皮都和原始 FBX 一致。

**方式 C**：文本编辑器打开 `bake_to_ue.py` → Run Script。它会把当前动作烘焙成
`root` 上的关键帧、删掉 RTG 约束，并另存为 `rigue5_rigified_baked.blend`。
（已验证：烘焙结果与原约束姿势逐帧误差 < 1e-5 m。）

## 姿态捕捉（截图 / 图片 → 自动摆姿势）

面板「角色工具」下面新增了 **姿态捕捉**：

- `图片 ➜ 姿态`：选一张图。
- `截图 ➜ 姿态`：调起 Windows 截图（Win+Shift+S），框选后自动识别。
- `剪贴板 ➜ 姿态`：先自己截图，再点这个按钮。
- 选项：`脚部贴地`、`深度`（0–1 滑杆，默认 0.7）、`镜像`、`躯干倾斜`、`头/颈转向`、
  `匹配朝向`、`四肢`（FK/IK，默认 FK）、`手指`（默认开）。`手指` 用 MHR70 的手部
  关节摆 5 根手指 × 3 节；SAM 3D Body 打开它时会顺手部精修（fp32 加载，ComfyUI 的
  fp16 路径有类型 bug），显存不足或精修失败会自动退回普通推理。`深度` 控制单图估出来的 3D 深度强度：
  正面截图觉得脚/腿前后错位时，可以降到 0.4–0.6；完全平面用 0。`匹配朝向` 会按
  参考的肩/髋朝向把整个角色绕 Z 转到相同方向（参考图侧身/背身时很有用）；如果
  角色有固定朝向或根运动，可以关掉。如果觉得某个东西估计不稳，可以直接关掉
  `躯干倾斜` 或 `头/颈转向`。
- `四肢` 默认 **FK**：按参考的肩→肘→腕、髋→膝→踝方向摆 FK 骨，肘/膝更贴近参考；
  如果更在意手/脚落点，切到 **IK**（手/脚位置精确，但肘/膝由 IK 平面决定）。
- 后端：`自动 / SAM 3D Body / InstantHMR / MediaPipe`。

识别结果只写 Rigify 控制器（`torso`、`shoulder`、`neck`、`head`、FK/IK 四肢控制器，
以及 `thumb.*` / `f_*.01-03` 手指控制器），不修改 `root`、UE 骨架、网格、蒙皮和
导出流程。现在摆身体（含躯干相对髋部的前后倾与扭转、头/颈朝向）+ 手腕/脚腕方向 +
手指。手指只取关节方向、不取长度，所以参考手比 Manny 大/小都不会把手拉长；每根
手指会做段长合理性检查，明显异常的整根跳过。

躯干的前后倾/扭转用“髋线 + 图像垂直方向”和“肩线 + 肩-髋轴”的相对旋转计算；
8° 以内当作单图 3D 噪声忽略，超过后按 0.9 缩放（上限 35°），避免“总是前倾”，
同时保留真实弯腰/侧倾的幅度。
头/颈只应用 yaw（±60°）和一半 pitch（±25°），不做 roll；脸/耳朵不可见时头跟随躯干。

### 后端与下载

| 后端 | 用途 | 需要的东西 |
| --- | --- | --- |
| **SAM 3D Body** | 质量最高，MHR70 的 70 个 3D 关键点（身体+手+脚） | `sam_3d_body_dinov3_bf16.safetensors`（约 2.83 GB）+ ComfyUI 的 `.venv` |
| **InstantHMR** | SAM 3D Body 的蒸馏版，同样的 70 个关键点，公开 ONNX | `instanthmr-medium-fit2.onnx` + `mhr-body.onnx`（约 96 MB） |
| **MediaPipe** | 轻量兜底 / bbox / 半身图 | `pose_landmarker_full.task`（约 9 MB） |

ComfyUI 用的转换版权重（推荐；键名和 ComfyUI 的 `SAM3DBody` 匹配）：

```bat
mkdir "D:\Comfy-Desktop\ComfyUI-Shared\models\detection"
curl -L -C - --retry 10 --retry-all-errors ^
  -o "D:\Comfy-Desktop\ComfyUI-Shared\models\detection\sam_3d_body_dinov3_bf16.safetensors" ^
  "https://hf-mirror.com/Comfy-Org/sam-3d-body/resolve/main/detection/sam_3d_body_dinov3_bf16.safetensors"
```

也可以下 `sam_3d_body_dinov3_int8_convrot.safetensors`（约 1.99 GB，量化版，显存更省）。
下载页：<https://huggingface.co/Comfy-Org/sam-3d-body>

> 原始 Meta 的 `model.ckpt`（Blendcap / ModelScope 的
> `facebook/sam-3d-body-dinov3`，约 2.1 GB）是给官方 `facebookresearch/sam-3d-body`
> repo 用的，**键名和 ComfyUI 的实现不兼容**（会报 missing/unexpected），不要用它跑
> 本面板的 ComfyUI 后端。本面板的自动后端只认 `models/detection` 下的
> `sam_3d_body_dinov3_*.safetensors`。

轻量兜底（放到 `%LOCALAPPDATA%\rigue5_pose\models`）：

- `https://hf-mirror.com/momolesang/InstantHMR/resolve/main/instanthmr-medium-fit2.onnx`
- `https://hf-mirror.com/momolesang/InstantHMR/resolve/main/mhr-body.onnx`
- MediaPipe：`https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task`

SAM 3D Body 优先用 ComfyUI 自带的实现和 Python 环境：

- 代码：`D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\comfy_extras\nodes_sam3d_body.py`
- Python：`D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\.venv\Scripts\python.exe`
  （Python 3.13 + torch 2.12.1+cu130）
- 权重放到 `models\detection\sam_3d_body_dinov3_bf16.safetensors` 后，ComfyUI 里也能
  直接加载 `SAM3DBody_Loader` / `SAM3DBody_Predict` 节点。

面板里的「检查环境」会显示当前可用的后端和路径。路径不对时可以在
`Scene` 的 `character_pose_*` 属性里覆盖（`ComfyUI Python`、`ComfyUI 根目录`、
`SAM 3D Body 权重`、`系统 Python`）。

helper 源码在 `_build/pose_helper.py`，由 `_build/add_character_ui.py` 写入
`.blend` 的 `pose_helper.py` 文本块；改了 helper 后要重新跑一次：

```bat
blender -b --factory-startup --python _build/add_character_ui.py
```

姿态映射的 headless 测试（不需要模型）：

```bat
blender -b --factory-startup --disable-autoexec rigue5_rigified.blend ^
  --python _build/verify_pose_capture.py
```

### 使用

1. 选中角色的 `rig`，进入 Pose Mode（或 Object Mode 也行）。
2. 在「姿态捕捉」里点 `图片 ➜ 姿态` / `截图 ➜ 姿态` / `剪贴板 ➜ 姿态`。
3. 识别时面板会显示阶段（检测人物框 / 加载模型 / 推理）和进度百分比；
   截图入口用 Win+Shift+S，点完后在弹出截图框里拖选。
4. 卡住时点「取消识别」；出错时点「打开日志」看 `last_error.log`。
5. 等状态显示「已应用 …」；控制器会被摆好。
6. 需要的话在 Action Editor 里给 `rig` K 帧；不 K 帧的话切帧会回到动作的姿势。

识别前会自动用 YOLO11m-pose 找人物框再裁给 3D 模型（模型在
`%LOCALAPPDATA%\rigue5_pose\models\yolo11m-pose.pt`）；找不到人物框时会退回
整图并在结果里给提示。

### 限制

- 本地模型对**真人 / 写实图**最好；卡通、风格化游戏截图可能识别失败或不准。
- 手指依赖 MHR70 的手部关节（SAM 3D Body / InstantHMR 提供）；手被遮挡、握持物体
  或极端透视时，手指方向可能不准。段长明显异常的整根手指会跳过。
- 半身图需要左右肩和左右髋都可见（否则会报错）。
- 单张图的深度是估算的；3/4 侧、遮挡、极端姿势可能偏差。倒立/手倒立目前只会给
  提示（提醒“按脚踩地处理”），不会自动把角色翻过来。
- FK 四肢按参考方向摆骨，肘/膝更准，但手/脚落在 Manny 自身骨长末端，和参考位置可能
  差几厘米；IK 模式手/脚位置精确，但肘/膝受这个 rig 的 IK 平面限制。两种模式可以在
  面板的 `四肢` 里切换。
- SAM 3D Body / InstantHMR 的权重分别受 SAM License / 非商用限制，使用前请确认。
- 截图入口仅 Windows。

## 注意

* 不要删 `RTG_CORRECTIVES` 里的空物体，也不要把它放进被排除（Exclude）的集合，
  否则对应骨骼会失去驱动。其中 `RTG_root__root` 负责把 `rig:root` 的位移和旋转
  传给 UE 骨架对象（根运动），删掉它根运动就没了。
* 不要直接点 Rigify 的 **Generate**：重建会重新生成 DEF 骨骼，辅助空物体的父级和
  约束会失效。要重建就运行 `_build/build_all.py`。
* 小白人是 A-pose 绑定的；手腕、肘部在极端角度下会有轻微挤压，这是 Manny 网格
  本身的蒙皮特性（它的前臂主要由 twist 骨骼驱动）。
