# -*- coding: utf-8 -*-
"""Tidy up the generated blend: collections, readme, viewport state."""
import bpy

BLEND = r"D:\Projects\UE5Anim\rigue5_rigified.blend"
bpy.ops.wm.open_mainfile(filepath=BLEND)

sc = bpy.context.scene
objs = bpy.data.objects


def ensure_coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        sc.collection.children.link(c)
    return c


def move_to(ob, coll):
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    coll.objects.link(ob)


manny = ensure_coll('Manny (UE5)')
rigify = ensure_coll('Rigify')

for name in ('SKM_Manny', 'root', 'SKM_Manny.001'):
    ob = objs.get(name)
    if ob:
        move_to(ob, manny)
for name in ('rig', 'metarig'):
    ob = objs.get(name)
    if ob:
        move_to(ob, rigify)

if 'metarig' in objs:
    objs['metarig'].hide_set(True)

# --- scene cleanup ----------------------------------------------------------
# the FBX import left an empty as the parent of the UE skeleton: it carries no
# transform that matters, so unparent (keeping the world matrix) and drop it
fbx_root = objs.get('SKM_Manny.001')
if fbx_root:
    for child in list(fbx_root.children):
        mw = child.matrix_world.copy()
        child.parent = None
        child.matrix_world = mw
    bpy.data.objects.remove(fbx_root, do_unlink=True)

# drop collections that hold nothing (e.g. the default "Collection"), lifting
# any nested collection up to the scene first
default_coll = bpy.data.collections.get('Collection')
if default_coll is not None and len(default_coll.objects) == 0:
    for child in list(default_coll.children):
        default_coll.children.unlink(child)
        if child.name not in [c.name for c in sc.collection.children]:
            sc.collection.children.link(child)
    bpy.data.collections.remove(default_coll)

for c in list(bpy.data.collections):
    if len(c.objects) == 0 and len(c.children) == 0:
        bpy.data.collections.remove(c)

# viewer images are not part of the asset
for img in list(bpy.data.images):
    if img.source == 'VIEWER':
        bpy.data.images.remove(img)

bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

# --- display defaults -------------------------------------------------------
# the UE skeleton is only the deform driver: its bones are long and point in
# odd directions, so keep it out of the viewport entirely
ue = objs.get('root')
if ue:
    ue.show_in_front = False
    ue.hide_set(True)
    ue.hide_render = True

rig_ob = objs['rig']
rig_ob.show_in_front = True          # widgets always on top of the mesh

# limbs start in IK, so keep the (inactive) FK controls hidden until the user
# flips IK_FK; with rig_ui.py running rigify toggles these by itself
for bc in rig_ob.data.collections:
    if 'FK' in bc.name:
        bc.is_visible = False

# the Manny cannot stretch: keep the rig's arms/legs at fixed length too, so the
# hand/foot widgets stay on the character
for side in ('L', 'R'):
    for b in ('upper_arm_parent.' + side, 'thigh_parent.' + side):
        if b in rig_ob.pose.bones:
            rig_ob.pose.bones[b]['IK_Stretch'] = 0.0

# bending the body must carry the neck and the head with it (otherwise the head
# stays upright / twists off the neck)
torso = rig_ob.pose.bones['torso']
torso['neck_follow'] = 1.0
torso['head_follow'] = 1.0

# the neck widget is generated with twice the radius of the head widget, so it
# reads as a huge hoop crossing the chest - shrink it into a collar
wgt = bpy.data.objects.get('WGT-rig_neck')
if wgt:
    for v in wgt.data.vertices:
        v.co.x *= 0.45
        v.co.z *= 0.45
    wgt.data.update()

# the helpers must stay evaluated by the depsgraph (they drive the constraints)
rtg = bpy.data.collections.get('RTG_CORRECTIVES')
if rtg:
    for o in rtg.objects:
        o.hide_set(True)
        o.hide_render = True

# remove leftover empty bone collections (the face rig was removed on purpose)
for arm in (objs['rig'], objs['metarig']):
    for bc in list(arm.data.collections):
        if len(bc.bones) == 0 and (bc.name.lower().startswith('face')
                                   or bc.name in ('ORG', 'MCH', 'DEF')):
            arm.data.collections.remove(bc)

# ------------------------------------------------------------------ readme
README = """Rigify => UE5 Manny  (由 rigue5.blend 自动生成)
=================================================

【文件结构】
  rig                 Rigify 控制器骨架 —— 用它摆姿势
  metarig             已按小白人关节位置对齐的元骨架（隐藏）
  root                UE5 Manny 原始骨架（SKM_Manny.FBX），网格绑在它身上
  SKM_Manny           小白人网格
  RTG_CORRECTIVES     隐藏空物体，把 Rigify 骨骼的旋转换算成 UE 骨骼的旋转
                      （不要删除、不要移动、不要放进被排除的集合）

  没有面部控制器：Manny 没有面部骨骼，元骨架里的面部骨骼已删除，
  生成的绑定只有身体 + 手指。

【怎么用】
  1. 选中 rig，进入 Pose Mode，像普通 Rigify 绑定一样操作；
     小白人会实时跟着动。
  2. 四肢默认 IK。想改用 FK：选中 upper_arm_parent.L / thigh_parent.L 这类
     骨骼，在 N 面板 Item 里把 IK_FK 滑块拉到 1。
  3. 控制器面板需要 rig_ui.py 运行：
     打开文件时选“允许执行脚本”，或 偏好设置 > 保存和加载 > 自动运行 Python 脚本。

【导出回 UE5】
  方式 A（推荐）：选中 root + SKM_Manny，文件 > 导出 > FBX，
      勾选 “Bake Animation / 烘焙动画”。约束会在烘焙时被采样成 UE 骨骼的关键帧。
  方式 B：在文本编辑器里打开 bake_to_ue.py 并运行，
      把当前动作烘焙成 root 上的关键帧并移除 RTG 约束（得到干净的可导出文件）。

【注意】
  * 不要删除 RTG_CORRECTIVES 中的空物体，否则对应骨骼失去驱动。
  * 不要直接点 Rigify 的 Generate：重建 rig 会重新生成 DEF 骨骼，
    空物体的父级和约束会失效，需要重新运行生成脚本。
  * 蒙皮权重、UE 骨架层级、骨骼名字都没有改动，动画可以直接回到 UE。
"""

text = bpy.data.texts.get('README_rigify_UE5')
if text is None:
    text = bpy.data.texts.new('README_rigify_UE5')
text.clear()
text.write(README)

sc.frame_set(1)
for o in bpy.data.objects:
    o.select_set(False)
objs['rig'].select_set(True)
bpy.context.view_layer.objects.active = objs['rig']

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
print("[finalize] saved", BLEND)
