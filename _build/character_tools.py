# -*- coding: utf-8 -*-
"""角色工具：在 3D 视图 N 面板「Rigify」标签里加一个「复制角色」按钮。

这段代码会被写进 .blend 的文本块 character_tools.py（use_module=True），
打开文件时自动运行；按钮会把当前角色整套（rig + UE 骨架 + 网格 + 重定向空物体）
复制一份，并重新指向副本自己的对象。
"""
import bpy
import re
from mathutils import Vector


def _find_rig(ob):
    """当前选中的可能是 rig，也可能是 UE 骨架，都换算回 rig。"""
    if ob is None or ob.type != 'ARMATURE':
        return None
    if any(o.name.startswith('RTG_') and o.parent is ob for o in bpy.data.objects):
        return ob
    helpers = set()
    for pb in ob.pose.bones:
        for c in pb.constraints:
            tgt = getattr(c, 'target', None)
            if tgt is not None and tgt.name.startswith('RTG_') and tgt.parent is not None:
                helpers.add(tgt.parent)
    if len(helpers) == 1:
        return next(iter(helpers))
    return None


def _character_parts(rig):
    """找出和这个 rig 配套的：重定向空物体、UE 骨架、网格。"""
    helpers = [o for o in bpy.data.objects
               if o.name.startswith('RTG_') and o.parent is rig]
    root = None
    for ob in bpy.data.objects:
        if ob.type != 'ARMATURE' or ob is rig:
            continue
        for pb in ob.pose.bones:
            for c in pb.constraints:
                tgt = getattr(c, 'target', None)
                if tgt is not None and tgt in helpers:
                    root = ob
                    break
            if root is not None:
                break
        if root is not None:
            break
    mesh = None
    if root is not None:
        for ob in bpy.data.objects:
            if ob.type == 'MESH' and any(m.type == 'ARMATURE' and m.object is root
                                         for m in ob.modifiers):
                mesh = ob
                break
    return helpers, root, mesh


def _strip_suffix(name):
    return re.sub(r'\.\d{3}$', '', name)


def duplicate_character(rig, prefix='B_', offset=(1.3, 0.0, 0.0)):
    helpers, root, mesh = _character_parts(rig)
    if root is None or mesh is None:
        raise RuntimeError('找不到这个角色的 UE 骨架或网格（RTG_ 空物体是否还在？）')

    group = [rig, root, mesh] + helpers
    hidden = {o: o.hide_get() for o in group}
    for o in group:
        o.hide_set(False)

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
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
        o.name = prefix + _strip_suffix(o.name)
        if o.data is not None:
            o.data.name = o.name

    new_rig = next((o for o in copies if o.type == 'ARMATURE'
                    and o.data.bones.get('DEF-spine')), None)
    new_root = next((o for o in copies if o.type == 'ARMATURE' and o is not new_rig), None)
    new_mesh = next((o for o in copies if o.type == 'MESH'
                     and len(o.data.vertices) > 10000), None)

    off = Vector(offset)
    for o in (new_rig, new_root):
        if o is not None:
            o.location = o.location + off

    coll = bpy.data.collections.get(prefix.rstrip('_') + ' character')
    if coll is None:
        coll = bpy.data.collections.new(prefix.rstrip('_') + ' character')
        bpy.context.scene.collection.children.link(coll)
    for o in copies:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
        o.hide_set(True)

    return new_rig.name if new_rig else '?', len(copies)


class CHARACTER_OT_duplicate(bpy.types.Operator):
    """把当前角色整套复制一份（骨架+网格+重定向空物体），互不影响"""
    bl_idname = 'character.duplicate_character'
    bl_label = '复制当前角色'
    bl_options = {'REGISTER', 'UNDO'}

    prefix: bpy.props.StringProperty(name='名称前缀', default='B_')
    offset: bpy.props.FloatVectorProperty(name='位置偏移', default=(1.3, 0.0, 0.0),
                                          subtype='TRANSLATION', unit='LENGTH')

    def execute(self, context):
        rig = _find_rig(context.active_object)
        if rig is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        try:
            name, count = duplicate_character(rig, self.prefix, self.offset)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, '已复制 %d 个对象，新骨架：%s' % (count, name))
        return {'FINISHED'}


def export_character(rig, filepath):
    """导出这个角色的 root + 网格，动画（含根运动）一起烘焙进 FBX。"""
    helpers, root, mesh = _character_parts(rig)
    if root is None or mesh is None:
        raise RuntimeError('找不到 UE 骨架或网格')
    hidden = root.hide_get()
    root.hide_set(False)
    for o in bpy.data.objects:
        o.select_set(False)
    root.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = root
    try:
        bpy.ops.export_scene.fbx(
            filepath=filepath,
            use_selection=True,
            object_types={'ARMATURE', 'MESH'},
            bake_anim=True,
            bake_anim_use_all_bones=True,
            bake_anim_use_nla_strips=False,
            bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=True,
            bake_anim_step=1,
            bake_anim_simplify_factor=0.0,
            add_leaf_bones=False,
            primary_bone_axis='Y',
            secondary_bone_axis='X',
        )
    finally:
        root.hide_set(hidden)
    return root.name


class CHARACTER_OT_toggle_ue(bpy.types.Operator):
    """在视口里显示/隐藏 UE 骨架，导出 FBX 前需要它可见可选"""
    bl_idname = 'character.toggle_ue_skeleton'
    bl_label = '显示 UE 骨架（导出用）'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = _find_rig(context.active_object)
        if rig is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        parts = _character_parts(rig)
        root = parts[1]
        mesh = parts[2]
        if root is None:
            self.report({'ERROR'}, '找不到 UE 骨架')
            return {'CANCELLED'}
        show = root.hide_get()
        root.hide_set(not show)
        if show:
            for o in bpy.data.objects:
                o.select_set(False)
            root.select_set(True)
            if mesh:
                mesh.select_set(True)
            self.report({'INFO'}, '已显示并选中 %s + 网格，可以导出 FBX 了' % root.name)
        else:
            self.report({'INFO'}, '已隐藏 UE 骨架')
        return {'FINISHED'}


class CHARACTER_OT_export_fbx(bpy.types.Operator):
    """把当前角色导出成 FBX（动画 + 根运动一起烘焙）"""
    bl_idname = 'character.export_fbx'
    bl_label = '导出 FBX（含根运动）'
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')

    def invoke(self, context, event):
        rig = _find_rig(context.active_object)
        if rig is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        if not self.filepath:
            base = bpy.path.basename(bpy.data.filepath)
            base = base.rsplit('.', 1)[0] if base else 'character'
            self.filepath = bpy.path.abspath('//%s_export.fbx' % base)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        rig = _find_rig(context.active_object)
        if rig is None:
            self.report({'ERROR'}, '请先选中角色的 rig')
            return {'CANCELLED'}
        path = bpy.path.ensure_ext(self.filepath, '.fbx')
        try:
            root_name = export_character(rig, path)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, '已导出 %s 到 %s' % (root_name, path))
        return {'FINISHED'}


class VIEW3D_PT_character_tools(bpy.types.Panel):
    bl_label = '角色工具'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Rigify'

    def draw(self, context):
        layout = self.layout
        ob = context.active_object
        is_rig = (ob is not None and ob.type == 'ARMATURE' and any(
            o.name.startswith('RTG_') and o.parent is ob for o in bpy.data.objects))
        col = layout.column(align=True)
        col.enabled = is_rig
        col.operator('character.duplicate_character', icon='DUPLICATE', text='复制当前角色')
        col.operator('character.toggle_ue_skeleton', icon='HIDE_OFF', text='显示/隐藏 UE 骨架')
        col.operator('character.export_fbx', icon='EXPORT', text='导出 FBX（含根运动）')
        if not is_rig:
            layout.label(text='先选中角色的 rig', icon='INFO')
        layout.label(text='根运动：物体模式下移动 rig', icon='BLANK1')


def register():
    for cls in (CHARACTER_OT_duplicate, CHARACTER_OT_export_fbx, CHARACTER_OT_toggle_ue,
                VIEW3D_PT_character_tools):
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            bpy.utils.unregister_class(cls)
            bpy.utils.register_class(cls)


register()
