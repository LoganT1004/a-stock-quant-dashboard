"""批量修复所有 .py 文件中的硬编码 Windows 路径"""
import os

# 文件中的实际字节：单反斜杠（在raw string里显示为\\）
OLD = b'C:\\Users\\ASUS\\WorkBuddy\\2026-08-03-11-17-59'
NEW = b"os.path.dirname(os.path.abspath(__file__))"

count = 0
for root, dirs, files in os.walk('.'):
    if '.git' in root or '__pycache__' in root:
        continue
    for f in files:
        if not f.endswith('.py'):
            continue
        fp = os.path.join(root, f)
        try:
            with open(fp, 'rb') as fobj:
                content = fobj.read()
        except:
            continue

        if OLD not in content:
            continue

        new_content = content.replace(OLD, NEW)

        if new_content == content:
            continue

        # 确保文件顶部有 import os
        if b'import os' not in new_content[:300]:
            lines = new_content.split(b'\n')
            inserted = False
            for i, line in enumerate(lines):
                if line.startswith(b'import ') or line.startswith(b'from '):
                    if b'import os' not in line and not inserted:
                        lines.insert(i, b'import os, sys')
                        inserted = True
                    break
            new_content = b'\n'.join(lines)

        with open(fp, 'wb') as fobj:
            fobj.write(new_content)
        count += 1
        print(f'  ✓ {fp}')

print(f'\n共修复 {count} 个文件')