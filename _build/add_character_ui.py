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
HELPER_SRC = os.path.join(HERE, 'pose_helper.py')

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if argv:
    BLEND = os.path.abspath(argv[0])

bpy.ops.wm.open_mainfile(filepath=BLEND)

with open(SRC, 'r', encoding='utf-8') as fh:
    code = fh.read()
compile(code, SRC, 'exec')

text = bpy.data.texts.get('character_tools.py')
if text is None:
    text = bpy.data.texts.new('character_tools.py')
text.clear()
text.write(code)
text.use_module = True

helper_code = None
if os.path.isfile(HELPER_SRC):
    with open(HELPER_SRC, 'r', encoding='utf-8') as fh:
        helper_code = fh.read()
    compile(helper_code, HELPER_SRC, 'exec')
    helper = bpy.data.texts.get('pose_helper.py')
    if helper is None:
        helper = bpy.data.texts.new('pose_helper.py')
    helper.clear()
    helper.write(helper_code)
    helper.use_module = False

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
print("[character-ui] text block written to", BLEND,
      "use_module =", text.use_module,
      "helper =", bool(helper_code))
