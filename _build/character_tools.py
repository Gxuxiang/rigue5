# -*- coding: utf-8 -*-
"""角色工具：在 3D 视图 N 面板「Rigify」标签里加一个「复制角色」按钮。

这段代码会被写进 .blend 的文本块 character_tools.py（use_module=True），
打开文件时自动运行；按钮会把当前角色整套（rig + UE 骨架 + 网格 + 重定向空物体）
复制一份，并重新指向副本自己的对象。
"""
import bpy
import math
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


# ---------------------------------------------------------------- 动作选择
# Blender 4.4+ 的 Action 分「槽位」（slot），每个槽位绑定一个物体。
# 动作列表只显示能驱动这个 rig 的，避免双角色时选到 B_rig 的动作。

def _action_slots(action):
    return list(getattr(action, 'slots', []) or [])


def _slot_matches_rig(slot, rig):
    if getattr(slot, 'target_id_type', 'OBJECT') != 'OBJECT':
        return False
    return (slot.name_display == rig.name
            or getattr(slot, 'identifier', '') == 'OB' + rig.name)


def _action_fits_rig(action, rig):
    slots = _action_slots(action)
    if not slots:          # 4.4 以前的旧动作，没有槽位概念
        return True
    return any(_slot_matches_rig(s, rig) for s in slots)


def _any_object_slot(action):
    slots = _action_slots(action)
    if not slots:
        return True
    return any(getattr(s, 'target_id_type', 'OBJECT') == 'OBJECT' for s in slots)


def actions_for_rig(rig):
    """当前 rig 能用的动作：优先按槽位名过滤；都被过滤掉时退回所有物体动作。"""
    acts = [a for a in bpy.data.actions if _action_fits_rig(a, rig)]
    if not acts:
        acts = [a for a in bpy.data.actions if _any_object_slot(a)]
    return sorted(acts, key=lambda a: a.name.lower())


def action_frame_range(action):
    start, end = action.frame_range
    start = int(math.floor(start + 0.5))
    end = int(math.ceil(end - 0.5))
    return start, max(start, end)


def _pick_action_slot(action, obj):
    """在动作的槽位里挑一个给 obj 用的（Blender 4.4+）。"""
    slots = _action_slots(action)
    if not slots:
        return None
    obj_slots = [s for s in slots
                 if getattr(s, 'target_id_type', 'OBJECT') == 'OBJECT']
    for s in obj_slots:
        if _slot_matches_rig(s, obj):
            return s
    return obj_slots[0] if obj_slots else slots[0]


def _assign_action(obj, action):
    """切到指定动作；切完如果槽位没自动对上，就手动补一个。"""
    ad = obj.animation_data or obj.animation_data_create()
    ad.action = action
    if hasattr(ad, 'action_slot') and getattr(ad, 'action_slot', None) is None:
        slot = _pick_action_slot(action, obj)
        if slot is not None:
            try:
                ad.action_slot = slot
            except (TypeError, AttributeError):
                pass
    return ad


def _capture_pose(obj):
    """记下物体和所有骨骼当前的变换，导出完用于还原。"""
    return {
        'object': (tuple(obj.location), tuple(obj.rotation_euler),
                   tuple(obj.rotation_quaternion), tuple(obj.rotation_axis_angle),
                   tuple(obj.scale)),
        'bones': {pb.name: (tuple(pb.location), tuple(pb.rotation_euler),
                            tuple(pb.rotation_quaternion),
                            tuple(pb.rotation_axis_angle), tuple(pb.scale))
                  for pb in obj.pose.bones},
    }


def _restore_pose(obj, state):
    obj.location = state['object'][0]
    obj.rotation_euler = state['object'][1]
    obj.rotation_quaternion = state['object'][2]
    obj.rotation_axis_angle = state['object'][3]
    obj.scale = state['object'][4]
    for name, vals in state['bones'].items():
        pb = obj.pose.bones.get(name)
        if pb is not None:
            (pb.location, pb.rotation_euler, pb.rotation_quaternion,
             pb.rotation_axis_angle, pb.scale) = vals


def _reset_pose(obj):
    """清到静止姿势。

    切动作时 Blender 不会重置动作里没有 K 帧的通道，会把上一段动作最后一帧的
    姿势/位移留在身上（根运动尤其明显：原地动作会带上前一段的位移）。
    导出前清一次，保证每个动作都是独立的。
    """
    obj.location = (0.0, 0.0, 0.0)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    obj.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    obj.scale = (1.0, 1.0, 1.0)
    for pb in obj.pose.bones:
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


def _menu_actions(context):
    """当前 rig 可选的动作；选中的不是 rig 时退回全部物体动作。"""
    rig = _find_rig(getattr(context, 'active_object', None))
    if rig is not None:
        return actions_for_rig(rig)
    return sorted((a for a in bpy.data.actions if _any_object_slot(a)),
                  key=lambda a: a.name.lower())


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


def export_character(rig, filepath, action=None):
    """导出这个角色的 root + 网格，动画（含根运动）一起烘焙进 FBX。

    action 为动作名（或 Action 对象）时，临时切到该动作、按它自己的帧范围导出，
    导出完再把当前动作和场景帧范围还原；为 None 时按场景时间轴导出（旧行为）。
    """
    helpers, root, mesh = _character_parts(rig)
    if root is None or mesh is None:
        raise RuntimeError('找不到 UE 骨架或网格')

    scene = bpy.context.scene
    ad = rig.animation_data
    saved_action = ad.action if ad else None
    saved_slot = getattr(ad, 'action_slot', None) if ad else None
    saved_range = (scene.frame_start, scene.frame_end)
    saved_frame = scene.frame_current
    saved_pose = None

    act = None
    if action:
        act = action if isinstance(action, bpy.types.Action) else bpy.data.actions.get(action)
        if act is None:
            raise RuntimeError('找不到动作：%s' % action)
        start, end = action_frame_range(act)

    hidden = root.hide_get()
    try:
        if act is not None:
            saved_pose = _capture_pose(rig)
            _reset_pose(rig)
            ad = _assign_action(rig, act)
            scene.frame_start, scene.frame_end = start, end
        root.hide_set(False)
        for o in bpy.data.objects:
            o.select_set(False)
        root.select_set(True)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = root
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
        if act is not None:
            scene.frame_start, scene.frame_end = saved_range
            if ad is not None:
                ad.action = saved_action
                if saved_action is not None and saved_slot is not None \
                        and hasattr(ad, 'action_slot'):
                    try:
                        ad.action_slot = saved_slot
                    except (TypeError, AttributeError):
                        pass
            scene.frame_set(saved_frame)
            if saved_pose is not None:
                _restore_pose(rig, saved_pose)
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
    action: bpy.props.StringProperty(
        name='动作', default='', options={'HIDDEN'},
        description='要导出的动作名；留空则用面板「动作」菜单的选择')

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
        action = self.action.strip()
        if not action:
            action = getattr(context.scene, 'character_export_action', '').strip()
        path = bpy.path.ensure_ext(self.filepath, '.fbx')
        try:
            root_name = export_character(rig, path, action or None)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if action:
            self.report({'INFO'}, '已导出 %s（动作 %s）到 %s' % (root_name, action, path))
        else:
            self.report({'INFO'}, '已导出 %s 到 %s' % (root_name, path))
        return {'FINISHED'}


class CHARACTER_OT_set_export_action(bpy.types.Operator):
    """记录「要导出的动作」；空字符串表示按场景时间轴导出"""
    bl_idname = 'character.set_export_action'
    bl_label = '选择导出动作'
    bl_options = {'INTERNAL'}

    action: bpy.props.StringProperty(default='')

    def execute(self, context):
        context.scene.character_export_action = self.action
        return {'FINISHED'}


class CHARACTER_MT_export_actions(bpy.types.Menu):
    bl_idname = 'CHARACTER_MT_export_actions'
    bl_label = '导出动作'

    def draw(self, context):
        layout = self.layout
        selected = getattr(context.scene, 'character_export_action', '')
        op = layout.operator('character.set_export_action',
                             text='当前时间轴（不切换动作）',
                             icon='CHECKMARK' if not selected else 'TIME')
        op.action = ''
        acts = _menu_actions(context)
        if acts:
            layout.separator()
        for act in acts:
            start, end = action_frame_range(act)
            op = layout.operator(
                'character.set_export_action',
                text='%s   （帧 %d - %d）' % (act.name, start, end),
                icon='CHECKMARK' if act.name == selected else 'ACTION')
            op.action = act.name


class VIEW3D_PT_character_tools(bpy.types.Panel):
    bl_label = '角色工具'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Rigify'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        ob = context.active_object
        is_rig = (ob is not None and ob.type == 'ARMATURE' and any(
            o.name.startswith('RTG_') and o.parent is ob for o in bpy.data.objects))
        col = layout.column(align=True)
        col.enabled = is_rig
        col.operator('character.duplicate_character', icon='DUPLICATE', text='复制当前角色')
        col.operator('character.toggle_ue_skeleton', icon='HIDE_OFF', text='显示/隐藏 UE 骨架')
        col.separator()
        selected = getattr(scene, 'character_export_action', '')
        act = bpy.data.actions.get(selected) if selected else None
        col.menu('CHARACTER_MT_export_actions', icon='ACTION',
                 text='动作：' + (act.name if act else '当前时间轴'))
        if selected and act is None:
            col.label(text='动作已不存在：%s' % selected, icon='ERROR')
        elif act is not None:
            start, end = action_frame_range(act)
            col.label(text='按动作帧范围：%d - %d' % (start, end), icon='ACTION')
        else:
            col.label(text='按时间轴导出：帧 %d - %d' % (
                scene.frame_start, scene.frame_end), icon='TIME')
        col.operator('character.export_fbx', icon='EXPORT', text='导出 FBX（含根运动）')
        if not is_rig:
            layout.label(text='先选中角色的 rig', icon='INFO')
        layout.label(text='根运动：物体模式下移动 rig', icon='BLANK1')


def register():
    for cls in (CHARACTER_OT_duplicate, CHARACTER_OT_export_fbx, CHARACTER_OT_toggle_ue,
                CHARACTER_OT_set_export_action, CHARACTER_MT_export_actions,
                VIEW3D_PT_character_tools):
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            bpy.utils.unregister_class(cls)
            bpy.utils.register_class(cls)
    bpy.types.Scene.character_export_action = bpy.props.StringProperty(
        name='动作',
        description='要导出的动作名（按动作自己的帧范围烘焙）；留空表示按场景时间轴',
        default='')


def unregister():
    if hasattr(bpy.types.Scene, 'character_export_action'):
        del bpy.types.Scene.character_export_action
    for cls in (VIEW3D_PT_character_tools, CHARACTER_MT_export_actions,
                CHARACTER_OT_set_export_action, CHARACTER_OT_toggle_ue,
                CHARACTER_OT_export_fbx, CHARACTER_OT_duplicate):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


register()
