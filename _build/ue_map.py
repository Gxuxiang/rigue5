"""Bone mapping between the UE5 Manny skeleton (`root`) and the Rigify rig (`rig`).

UE names come from SKM_Manny.FBX (UE5 Manny, 160 bones incl. deform helpers).
Rigify names come from the `metarig` in rigue5.blend (Basic Human + face).
"""

FINGERS = [('index', 'palm.01', 'f_index'), ('middle', 'palm.02', 'f_middle'),
           ('ring', 'palm.03', 'f_ring'), ('pinky', 'palm.04', 'f_pinky')]


def build_retarget_map():
    """UE bone -> [(rigify DEF bone, influence), ...]"""
    m = {}

    # ---- spine / head -------------------------------------------------
    # The metarig was fitted to the Manny joints like this:
    #   spine     pelvis    -> spine_01        (DEF-spine)
    #   spine.001 spine_01  -> spine_02        (DEF-spine.001)
    #   spine.002 spine_02  -> spine_03        (DEF-spine.002)
    #   spine.003 spine_03  -> spine_05        (DEF-spine.003)
    #   spine.004 spine_05  -> neck_01         (DEF-spine.004)
    #   spine.005 neck_01   -> head joint      (DEF-spine.005)
    #   spine.006 head joint-> head top        (DEF-spine.006)
    # so every UE joint copies the DEF bone that starts at the same joint.
    # (the head bone has to start at the *Manny's* head joint, not at neck_02,
    #  otherwise the head widget swings off the head when the neck turns)
    m['pelvis'] = [('DEF-spine', 1.0)]
    m['spine_01'] = [('DEF-spine.001', 1.0)]
    m['spine_02'] = [('DEF-spine.002', 1.0)]
    m['spine_03'] = [('DEF-spine.003', 1.0)]
    m['spine_04'] = [('DEF-spine.003', 1.0)]
    # spine_05 is the base of the neck: it follows the rig's neck base, but the
    # clavicles hang off it, so their position is pinned separately in build_rig
    m['spine_05'] = [('DEF-spine.004', 1.0)]
    m['neck_01'] = [('DEF-spine.005', 1.0)]
    m['neck_02'] = [('DEF-spine.005', 1.0)]
    m['head'] = [('DEF-spine.006', 1.0)]
    m['spine_04_latissimus_l'] = [('DEF-spine.003', 1.0)]
    m['spine_04_latissimus_r'] = [('DEF-spine.003', 1.0)]

    for s, S in (('l', 'L'), ('r', 'R')):
        # ---- shoulder / arm -------------------------------------------
        m['clavicle_' + s] = [('DEF-shoulder.%s' % S, 1.0)]
        m['clavicle_out_' + s] = [('DEF-shoulder.%s' % S, 1.0)]
        m['clavicle_scap_' + s] = [('DEF-shoulder.%s' % S, 1.0)]
        m['clavicle_pec_' + s] = [('DEF-spine.003', 1.0)]

        m['upperarm_' + s] = [('DEF-upper_arm.%s' % S, 1.0)]
        # UE twist bones distribute the twist between the two joints; reproduce
        # that by blending the rotation of the parent and child DEF bones.
        m['upperarm_twist_01_' + s] = [('DEF-upper_arm.%s' % S, 1.0)]
        m['upperarm_twist_02_' + s] = [('DEF-upper_arm.%s' % S, 1.0)]
        for n in ('upperarm_correctiveRoot_', 'upperarm_bck_', 'upperarm_fwd_',
                  'upperarm_in_', 'upperarm_out_', 'upperarm_twistCor_01_',
                  'upperarm_twistCor_02_', 'upperarm_tricep_', 'upperarm_bicep_'):
            m[n + s] = [('DEF-upper_arm.%s' % S, 1.0)]

        m['lowerarm_' + s] = [('DEF-forearm.%s' % S, 1.0)]
        m['lowerarm_twist_01_' + s] = [('DEF-forearm.%s' % S, 1.0)]
        m['lowerarm_twist_02_' + s] = [('DEF-forearm.%s' % S, 1.0)]
        for n in ('lowerarm_correctiveRoot_', 'lowerarm_bck_', 'lowerarm_fwd_',
                  'lowerarm_in_', 'lowerarm_out_'):
            m[n + s] = [('DEF-forearm.%s' % S, 1.0)]

        m['hand_' + s] = [('DEF-hand.%s' % S, 1.0)]
        m['wrist_inner_' + s] = [('DEF-hand.%s' % S, 1.0)]
        m['wrist_outer_' + s] = [('DEF-hand.%s' % S, 1.0)]
        m['weapon_' + s] = [('DEF-hand.%s' % S, 1.0)]

        # ---- fingers --------------------------------------------------
        for ue_f, palm, rg_f in FINGERS:
            m['%s_metacarpal_%s' % (ue_f, s)] = [('DEF-%s.%s' % (palm, S), 1.0)]
            for i in (1, 2, 3):
                m['%s_0%d_%s' % (ue_f, i, s)] = [('DEF-%s.0%d.%s' % (rg_f, i, S), 1.0)]
        for i in (1, 2, 3):
            m['thumb_0%d_%s' % (i, s)] = [('DEF-thumb.0%d.%s' % (i, S), 1.0)]

        # ---- leg ------------------------------------------------------
        m['thigh_' + s] = [('DEF-thigh.%s' % S, 1.0)]
        m['thigh_twist_01_' + s] = [('DEF-thigh.%s' % S, 1.0)]
        m['thigh_twist_02_' + s] = [('DEF-thigh.%s' % S, 1.0)]
        for n in ('thigh_correctiveRoot_', 'thigh_bck_', 'thigh_fwd_',
                  'thigh_out_', 'thigh_in_', 'thigh_bck_lwr_', 'thigh_fwd_lwr_'):
            m[n + s] = [('DEF-thigh.%s' % S, 1.0)]

        m['calf_' + s] = [('DEF-shin.%s' % S, 1.0)]
        m['calf_twist_01_' + s] = [('DEF-shin.%s' % S, 1.0)]
        m['calf_twist_02_' + s] = [('DEF-shin.%s' % S, 1.0)]
        for n in ('calf_correctiveRoot_', 'calf_knee_', 'calf_kneeBack_'):
            m[n + s] = [('DEF-shin.%s' % S, 1.0)]

        m['foot_' + s] = [('DEF-foot.%s' % S, 1.0)]
        m['ankle_fwd_' + s] = [('DEF-foot.%s' % S, 1.0)]
        m['ankle_bck_' + s] = [('DEF-foot.%s' % S, 1.0)]
        m['ball_' + s] = [('DEF-toe.%s' % S, 1.0)]

    return m


# Bones that must NOT be driven (IK helpers / markers of the UE skeleton).
SKIP = {'root', 'ik_foot_root', 'ik_foot_l', 'ik_foot_r', 'ik_hand_root',
        'ik_hand_gun', 'ik_hand_l', 'ik_hand_r', 'interaction', 'center_of_mass'}


def build_fit_map():
    """metarig bone -> (head source, tail source).  Sources are UE bone names
    (use that bone's head) or ('TAIL', bone) or explicit vectors."""
    fit = [
        ('spine',        ('H', 'pelvis'),      ('H', 'spine_01')),
        ('spine.001',    ('H', 'spine_01'),    ('H', 'spine_02')),
        ('spine.002',    ('H', 'spine_02'),    ('H', 'spine_03')),
        ('spine.003',    ('H', 'spine_03'),    ('H', 'spine_05')),
        ('spine.004',    ('H', 'spine_05'),    ('H', 'neck_01')),
        ('spine.005',    ('H', 'neck_01'),     ('H', 'head')),
        ('spine.006',    ('H', 'head'),        ('TOP', 'head')),
        ('pelvis.L',     ('H', 'pelvis'),      None),
        ('pelvis.R',     ('H', 'pelvis'),      None),
    ]
    for s, S in (('l', 'L'), ('r', 'R')):
        fit += [
            ('shoulder.%s' % S,  ('H', 'clavicle_' + s),   ('H', 'upperarm_' + s)),
            ('upper_arm.%s' % S, ('H', 'upperarm_' + s),   ('H', 'lowerarm_' + s)),
            ('forearm.%s' % S,   ('H', 'lowerarm_' + s),   ('H', 'hand_' + s)),
            ('hand.%s' % S,      ('H', 'hand_' + s),       ('H', 'middle_01_' + s)),
            ('thigh.%s' % S,     ('H', 'thigh_' + s),      ('H', 'calf_' + s)),
            ('shin.%s' % S,      ('H', 'calf_' + s),       ('H', 'foot_' + s)),
            ('foot.%s' % S,      ('H', 'foot_' + s),       ('H', 'ball_' + s)),
            ('toe.%s' % S,       ('H', 'ball_' + s),       ('TOE', 'ball_' + s)),
            ('heel.02.%s' % S,   ('HEEL', 'foot_' + s),    ('HEELX', 'foot_' + s)),
        ]
        for i, (ue_f, palm, rg_f) in enumerate(FINGERS, start=1):
            fit += [
                ('%s.%s' % (palm, S), ('H', '%s_metacarpal_%s' % (ue_f, s)),
                 ('H', '%s_01_%s' % (ue_f, s))),
                ('%s.01.%s' % (rg_f, S), ('H', '%s_01_%s' % (ue_f, s)),
                 ('H', '%s_02_%s' % (ue_f, s))),
                ('%s.02.%s' % (rg_f, S), ('H', '%s_02_%s' % (ue_f, s)),
                 ('H', '%s_03_%s' % (ue_f, s))),
                ('%s.03.%s' % (rg_f, S), ('H', '%s_03_%s' % (ue_f, s)),
                 ('TFING', '%s_03_%s' % (ue_f, s))),
            ]
        fit += [
            ('thumb.01.%s' % S, ('H', 'thumb_01_%s' % s), ('H', 'thumb_02_%s' % s)),
            ('thumb.02.%s' % S, ('H', 'thumb_02_%s' % s), ('H', 'thumb_03_%s' % s)),
            ('thumb.03.%s' % S, ('H', 'thumb_03_%s' % s), ('TFING', 'thumb_03_%s' % s)),
        ]
    return fit
