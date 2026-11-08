# -*- coding: utf-8 -*-
"""复制出一个独立的第二角色（Rigify 骨架 + 小白人网格 + 重定向空物体）。

用法：在 Blender 文本编辑器里打开本文件 → Run Script；
或命令行 blender -b rigue5_rigified.blend --python duplicate_character.py

脚本会整体复制 rig / root / SKM_Manny / RTG_ 空物体，把副本内部的父子关系和
约束重新指向副本自己（不共享），重命名成 B_xxx，放进新集合并在 X 轴错开。
原角色不受影响。
"""
import bpy
import re
from mathutils import Vector

SRC_RIG = 'rig'
SRC_ROOT = 'root'
SRC_MESH = 'SKM_Manny'
PREFIX = 'B_'
OFFSET = Vector((1.3, 0.0, 0.0))


def strip_suffix(name):
    return re.sub(r'\.\d{3}$', '', name)


def main():
    rig = bpy.data.objects[SRC_RIG]
    root = bpy.data.objects[SRC_ROOT]
    mesh = bpy.data.objects[SRC_MESH]
    helpers = [o for o in bpy.data.objects if o.name.startswith('RTG_')]
    group = [rig, root, mesh] + helpers

    hidden = {o: o.hide_get() for o in group}
    for o in group:
        o.hide_set(False)

    for o in bpy.data.objects:
        o.select_set(False)
    for o in group:
        o.select_set(True)
    bpy.context.view_layer.objects.active = rig

    before = set(bpy.data.objects)
    bpy.ops.object.duplicate(linked=False)
    copies = [o for o in bpy.data.objects if o not in before]
    for o, h in hidden.items():
        o.hide_set(h)

    for o in copies:
        o.name = PREFIX + strip_suffix(o.name)
        if o.data is not None:
            o.data.name = o.name

    new_rig = next(o for o in copies if o.type == 'ARMATURE' and o.data.bones.get('DEF-spine'))
    new_root = next(o for o in copies if o.type == 'ARMATURE' and o is not new_rig)
    new_mesh = next(o for o in copies if o.type == 'MESH' and len(o.data.vertices) > 10000)

    for o in (new_rig, new_root):
        o.location = o.location + OFFSET

    coll = bpy.data.collections.new(PREFIX.rstrip('_') + ' character')
    bpy.context.scene.collection.children.link(coll)
    for o in copies:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    for o in copies:
        o.hide_set(True)

    # ---------------- verification ----------------
    print("new rig :", new_rig.name)
    print("new root:", new_root.name)
    print("new mesh:", new_mesh.name)

    wrong_target = []
    for pb in new_root.pose.bones:
        for c in pb.constraints:
            if c.name.startswith('RTG-') and c.target is not None and c.target not in copies:
                wrong_target.append((pb.name, c.name, c.target.name))
    print("constraints pointing outside the copy:", len(wrong_target))
    for w in wrong_target[:5]:
        print("   ", w)

    bad_parent = [o.name for o in copies if o.parent is not None and o.parent not in copies]
    print("objects still parented outside the copy:", len(bad_parent), bad_parent[:5])

    if new_mesh.modifiers:
        print("new mesh armature modifier ->", new_mesh.modifiers[0].object.name)

    bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    print("saved")


main()
