# -*- coding: utf-8 -*-
"""把 character_tools.py 写进 blend 的文本块，并设成打开时自动运行。"""
import bpy
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BLEND = r"D:\Projects\UE5Anim\rigue5_rigified.blend"
SRC = os.path.join(HERE, 'character_tools.py')

bpy.ops.wm.open_mainfile(filepath=BLEND)

code = io = None
with open(SRC, 'r', encoding='utf-8') as fh:
    code = fh.read()

text = bpy.data.texts.get('character_tools.py')
if text is None:
    text = bpy.data.texts.new('character_tools.py')
text.clear()
text.write(code)
text.use_module = True

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
print("[character-ui] text block written, use_module =", text.use_module)
