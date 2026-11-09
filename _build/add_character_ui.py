# -*- coding: utf-8 -*-
"""把 character_tools.py 写进 blend 的文本块，并设成打开时自动运行。

默认写入仓库里的 rigue5_rigified.blend；也可以用命令行指定别的文件：
  blender -b --python _build/add_character_ui.py -- "D:/path/to/work.blend"
"""
import bpy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BLEND = os.path.join(os.path.dirname(HERE), 'rigue5_rigified.blend')
SRC = os.path.join(HERE, 'character_tools.py')

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if argv:
    BLEND = os.path.abspath(argv[0])

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
print("[character-ui] text block written to", BLEND, "use_module =", text.use_module)
