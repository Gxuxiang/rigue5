"""Fit the Rigify metarig to the UE5 Manny skeleton, regenerate the rig and
retarget the Manny (`root` armature) to the generated Rigify controls.

Run:  blender -b --factory-startup --python build_rig.py
"""
import bpy
import addon_utils
import sys
import os
import traceback
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ue_map

BLEND_IN = r"D:\Projects\UE5Anim\rigue5.blend"
BLEND_OUT = r"D:\Projects\UE5Anim\rigue5_rigified.blend"


def log(*a):
    print("[build]", *a)
    sys.stdout.flush()


bpy.ops.preferences.addon_enable(module='rigify')
bpy.ops.wm.open_mainfile(filepath=BLEND_IN)

mt = bpy.data.objects['metarig']
ue = bpy.data.objects['root']
mesh = bpy.data.objects['SKM_Manny']


def eval_verts():
    dg = bpy.context.evaluated_depsgraph_get()
    ob = mesh.evaluated_get(dg)
    me = ob.to_mesh()
    co = [ob.matrix_world @ v.co for v in me.vertices]
    ob.to_mesh_clear()
    return co


rest_ref = eval_verts()
log("reference verts", len(rest_ref))

# ---------------------------------------------------------------- fit metarig
uew = ue.matrix_world
mtw_inv = mt.matrix_world.inverted()


def ue_head(n):
    return uew @ ue.data.bones[n].head_local


def ue_tail(n):
    return uew @ ue.data.bones[n].tail_local


def resolve(spec, bone_name):
    kind, src = spec
    if kind == 'H':
        return ue_head(src)
    if kind == 'T':
        return ue_tail(src)
    raise ValueError(kind)


# remove the whole face sub-rig: the Manny has no face bones
face_root = mt.data.bones.get('face')
face_names = []


def collect(b):
    face_names.append(b.name)
    for c in b.children:
        collect(c)


if face_root:
    collect(face_root)

bpy.context.view_layer.objects.active = mt
bpy.ops.object.mode_set(mode='EDIT')
ebs = mt.data.edit_bones
for name in reversed(face_names):
    if name in ebs:
        ebs.remove(ebs[name])
log("removed face bones:", len(face_names), "remaining:", len(ebs))

fit = ue_map.build_fit_map()
# hierarchy order so connected children inherit the parent tail
order = {b.name: i for i, b in enumerate(sorted(mt.data.bones, key=lambda b: 0))}


def depth(b):
    d = 0
    while b.parent:
        b = b.parent
        d += 1
    return d


fit.sort(key=lambda e: depth(mt.data.bones[e[0]]) if e[0] in mt.data.bones else 99)

missing = [e[0] for e in fit if e[0] not in ebs]
if missing:
    log("WARNING missing metarig bones:", missing)

def heel_point(foot_name):
    f = ue_head(foot_name)
    sgn = 1.0 if f.x > 0 else -1.0
    return Vector((f.x - 0.038 * sgn, f.y + 0.030, 0.0))


for mt_name, hspec, tspec in fit:
    if mt_name not in ebs:
        continue
    eb = ebs[mt_name]
    if hspec[0] in ('HEEL', 'HEELX'):
        h = heel_point(hspec[1])
    else:
        h = resolve(hspec, mt_name)
    if tspec is None:
        if mt_name == 'pelvis.L':
            t = ue_head('thigh_l') + Vector((0, 0, 0.07))
        elif mt_name == 'pelvis.R':
            t = ue_head('thigh_r') + Vector((0, 0, 0.07))
        else:
            t = eb.tail
    elif tspec[0] == 'TOP':
        hh = ue_head(tspec[1])
        t = Vector((hh.x, hh.y, 1.78))
    elif tspec[0] == 'TOE':
        b = ue_head(tspec[1])
        f = ue_head('foot_' + mt_name[-1].lower())
        d = b - f
        d.z = 0.0
        d.normalize()
        t = b + d * 0.07
    elif tspec[0] == 'TFING':
        # the last phalanx: the FBX bone's own tail direction is meaningless,
        # so continue the finger's direction from the previous joint instead
        b = ue.data.bones[tspec[1]]
        hh = uew @ b.head_local
        ph = uew @ b.parent.head_local if b.parent else hh - Vector((0, 0, 0.02))
        d = hh - ph
        if d.length < 1e-6:
            d = Vector((0, 0, 0.02))
        d.normalize()
        length = ((uew @ b.tail_local) - (uew @ b.head_local)).length
        t = hh + d * max(length, 0.015)
    elif tspec[0] == 'HEEL':
        t = heel_point(tspec[1])
    elif tspec[0] == 'HEELX':
        hh = heel_point(tspec[1])
        sgn = 1.0 if hh.x > 0 else -1.0
        t = hh + Vector((0.08 * sgn, 0.0, 0.0))
    else:
        t = resolve(tspec, mt_name)

    h = mtw_inv @ h
    t = mtw_inv @ t
    if not eb.use_connect:
        eb.head = h
    if (t - eb.head).length < 1e-4:
        t = eb.head + Vector((0, 0, 0.01))
    eb.tail = t

bpy.ops.object.mode_set(mode='OBJECT')
log("metarig fitted: %d bones" % len(mt.data.bones))

# ------------------------------------------------------------- regenerate rig
old_rig = bpy.data.objects.get('rig')
bpy.ops.object.select_all(action='DESELECT')
mt.select_set(True)
bpy.context.view_layer.objects.active = mt
try:
    bpy.ops.pose.rigify_generate()
except Exception:
    traceback.print_exc()
    raise

rig = bpy.data.objects.get('rig')
if rig is None or rig == old_rig:
    rig = mt.data.rigify_target_rig
log("rig bones:", len(rig.data.bones))
log("DEF bones:", len([b for b in rig.data.bones if b.name.startswith('DEF-')]))

# ---------------------------------------------------------------- root motion
# UE writes root motion on the skeleton's root *node*: exporting an animation
# from UE gives an FBX whose top node carries the translation (Blender imports
# that as the armature object's animation, with 160 bones and no "root" bone).
# So we keep the armature object as the root and drive its location instead of
# adding an extra root bone - that matches what UE produces and expects.

# --------------------------------------------------------------- retargeting
# The UE skeleton was imported from FBX, so its bone rest orientations have
# nothing in common with the rig's DEF bones.  A plain copy-rotation would
# therefore twist the character.  A small empty per (UE bone, DEF bone) pair
# carries the constant rest offset  C = rig_rest^-1 * ue_rest :  the empty is
# bone-parented to the DEF bone (so its world matrix is rig_pose * C) and the
# UE bone copies its world rotation from that empty.
rt = ue_map.build_retarget_map()
rig_bones = set(rig.data.bones.keys())

# collection for the helpers
coll = bpy.data.collections.get('RTG_CORRECTIVES')
if coll is None:
    coll = bpy.data.collections.new('RTG_CORRECTIVES')
    bpy.context.scene.collection.children.link(coll)
else:
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)

# remove helpers from previous runs
for o in list(bpy.data.objects):
    if o.name.startswith('RTG_') and o.type == 'EMPTY':
        bpy.data.objects.remove(o, do_unlink=True)

problems = []
pending = []   # (empty, ue_bone, rig_bone, influence)
for ue_bone, entries in sorted(rt.items()):
    pb = ue.pose.bones.get(ue_bone)
    if pb is None:
        problems.append('missing UE bone ' + ue_bone)
        continue
    for c in list(pb.constraints):
        if c.name.startswith('RTG-'):
            pb.constraints.remove(c)
    for rg_bone, inf in entries:
        if rg_bone not in rig_bones:
            problems.append('missing rig bone ' + rg_bone + ' for ' + ue_bone)
            continue
        e = bpy.data.objects.new('RTG_%s__%s' % (ue_bone, rg_bone), None)
        coll.objects.link(e)
        e.empty_display_type = 'PLAIN_AXES'
        e.empty_display_size = 0.02
        e.hide_render = True
        e.parent = rig
        e.parent_type = 'BONE'
        e.parent_bone = rg_bone
        pending.append((e, ue_bone, rg_bone, inf))

# extra helper that carries the root motion: it sits at the world origin at rest
# and rides on DEF-spine, so the root bone gets exactly the rig's translation
root_empty = bpy.data.objects.new('RTG_root__DEF-spine', None)
coll.objects.link(root_empty)
root_empty.empty_display_type = 'PLAIN_AXES'
root_empty.empty_display_size = 0.05
root_empty.hide_render = True
root_empty.parent = rig
root_empty.parent_type = 'BONE'
root_empty.parent_bone = 'DEF-spine'
pending.append((root_empty, 'root', 'DEF-spine', 1.0))

bpy.context.view_layer.update()

# place every helper so that, at rest, it coincides with the UE bone's rest
# orientation relative to the DEF bone it is parented to.
# Bone parenting puts the object at the bone tail:  P = rig_world @ bone @ T(0,len,0)
targets = {}
for e, ue_bone, rg_bone, inf in pending:
    rig_rest = rig.matrix_world @ rig.data.bones[rg_bone].matrix_local
    if ue_bone == 'root':
        ue_rest = Matrix.Identity(4)      # the armature object's own space
    else:
        ue_rest = ue.matrix_world @ ue.data.bones[ue_bone].matrix_local
    # at rest the helper must sit exactly on the UE bone's rest orientation;
    # its basis (rig_rest^-1 * ue_rest) then makes it follow as  rig_pose * C
    if ue_bone == 'root':
        desired = (Matrix.Translation(ue_rest.to_translation())
                   @ ue_rest.to_quaternion().to_matrix().to_4x4())
    else:
        desired = Matrix.Translation(rig_rest.to_translation()) @ ue_rest.to_quaternion().to_matrix().to_4x4()
    pb = rig.pose.bones[rg_bone]
    P = rig.matrix_world @ pb.matrix @ Matrix.Translation((0, pb.bone.length, 0))
    e.matrix_basis = P.inverted() @ desired
    targets[e.name] = desired
    e.hide_set(True)
    if e.name == 'RTG_thigh_l__DEF-thigh.L':
        log("PLACE thigh: desired q", [round(v, 4) for v in desired.to_quaternion()],
            "P q", [round(v, 4) for v in P.to_quaternion()],
            "basis q", [round(v, 4) for v in e.matrix_basis.to_quaternion()])

bpy.context.view_layer.update()
# verify the helpers landed on the wanted matrices
dg = bpy.context.evaluated_depsgraph_get()
errs = []
for e, ue_bone, rg_bone, inf in pending:
    cur = e.evaluated_get(dg).matrix_world
    want = targets[e.name]
    errs.append(((cur.to_quaternion().rotation_difference(want.to_quaternion()).angle),
                 (cur.to_translation() - want.to_translation()).length))
log("helper placement: max rot err %.6f deg, max loc err %.6f m"
    % (max(e[0] for e in errs), max(e[1] for e in errs)))

added = 0
for e, ue_bone, rg_bone, inf in pending:
    if ue_bone == 'root':
        continue    # handled below as an object-level constraint
    pb = ue.pose.bones[ue_bone]
    c = pb.constraints.new('COPY_ROTATION')
    c.name = 'RTG-rot:%s' % rg_bone
    c.target = e
    c.owner_space = 'WORLD'
    c.target_space = 'WORLD'
    c.mix_mode = 'REPLACE'
    c.use_offset = False
    c.influence = inf
    added += 1

# root motion: the armature object itself rides on DEF-spine (the rig's body
# motion), and the pelvis keeps only its rotation - exactly like the FBX that
# UE produces for a root-motion animation
for c in list(ue.constraints):
    if c.name.startswith('RTG-'):
        ue.constraints.remove(c)
cl = ue.constraints.new('COPY_LOCATION')
cl.name = 'RTG-loc:root'
cl.target = bpy.data.objects['RTG_root__DEF-spine']
cl.owner_space = 'WORLD'
cl.target_space = 'WORLD'
cl.use_offset = False
cl.head_tail = 0.0

# the pelvis must not copy the translation any more (the object carries it)
pb = ue.pose.bones['pelvis']
for c in list(pb.constraints):
    if c.name.startswith('RTG-loc'):
        pb.constraints.remove(c)

# The Manny's clavicles hang off spine_05, which now follows the rig's neck
# base: pin their position to the rig's shoulder so turning the neck does not
# drag the arms around.
for side, S in (('l', 'L'), ('r', 'R')):
    pb = ue.pose.bones['clavicle_' + side]
    for c in list(pb.constraints):
        if c.name.startswith('RTG-loc'):
            pb.constraints.remove(c)
    cl = pb.constraints.new('COPY_LOCATION')
    cl.name = 'RTG-loc:DEF-shoulder.' + S
    cl.target = rig
    cl.subtarget = 'DEF-shoulder.' + S
    cl.owner_space = 'WORLD'
    cl.target_space = 'WORLD'
    cl.use_offset = False
    cl.head_tail = 0.0

log("helpers:", len(pending), "constraints added:", added, "problems:", problems)

bpy.context.view_layer.update()

bpy.context.view_layer.update()

# debug one helper
_dbg = pending[0]
_e = _dbg[0]
dg = bpy.context.evaluated_depsgraph_get()
log("DBG helper", _e.name)
log("   target  ", [round(v, 4) for v in targets[_e.name].to_quaternion()], [round(v, 4) for v in targets[_e.name].to_translation()])
log("   eval    ", [round(v, 4) for v in _e.evaluated_get(dg).matrix_world.to_quaternion()], [round(v, 4) for v in _e.evaluated_get(dg).matrix_world.to_translation()])
log("   orig    ", [round(v, 4) for v in _e.matrix_world.to_quaternion()], [round(v, 4) for v in _e.matrix_world.to_translation()])

# ------------------------------------------------------------ rest-pose check
rest_now = eval_verts()
maxd = max((a - b).length for a, b in zip(rest_ref, rest_now))
log("rest pose max vertex deviation: %.6f" % maxd)

# ------------------------------------------------------- posed accuracy check
import math
R = rig.pose.bones
R['upper_arm_fk.L'].rotation_mode = 'XYZ'
R['upper_arm_fk.L'].rotation_euler = (math.radians(-55), 0, 0)
R['forearm_fk.L'].rotation_mode = 'XYZ'
R['forearm_fk.L'].rotation_euler = (0, 0, math.radians(-35))
R['thigh_fk.L'].rotation_mode = 'XYZ'
R['thigh_fk.L'].rotation_euler = (math.radians(40), 0, 0)
R['shin_fk.L'].rotation_mode = 'XYZ'
R['shin_fk.L'].rotation_euler = (math.radians(-60), 0, 0)
R['spine_fk.001'].rotation_mode = 'XYZ'
R['spine_fk.001'].rotation_euler = (math.radians(12), 0, math.radians(10))
R['torso'].location = (0, 0, 0.05)
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
e_ue = ue.evaluated_get(dg)
e_rig = rig.evaluated_get(dg)


def wq(arm, name, mw):
    return (mw @ arm.pose.bones[name].matrix).to_quaternion()


def restq(arm, name, mw):
    return (mw @ arm.pose.bones[name].bone.matrix_local).to_quaternion()


worst = []
single_ok = {b for b, e in rt.items() if len(e) == 1}
for ue_bone, entries in sorted(rt.items()):
    if ue_bone not in single_ok:
        continue
    rb = entries[0][0]
    want = (wq(e_rig, rb, rig.matrix_world)
            @ restq(e_rig, rb, rig.matrix_world).inverted()
            @ restq(ue, ue_bone, ue.matrix_world))
    err = math.degrees(wq(e_ue, ue_bone, ue.matrix_world).rotation_difference(want).angle)
    worst.append((err, ue_bone, rb))
worst.sort(reverse=True)
log("posed retarget error: max %.4f deg, mean %.4f deg (%d single-target bones)"
    % (worst[0][0], sum(w[0] for w in worst) / len(worst), len(worst)))
for w in worst[:5]:
    log("   worst %-22s <- %-22s %.4f deg" % (w[1], w[2], w[0]))

# reset the rig to its rest pose before saving
for pb in rig.pose.bones:
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.context.view_layer.update()
rest_final = eval_verts()
log("final rest deviation after reset: %.6f"
    % max((a - b).length for a, b in zip(rest_ref, rest_final)))

bpy.ops.wm.save_as_mainfile(filepath=BLEND_OUT)
log("saved", BLEND_OUT)
