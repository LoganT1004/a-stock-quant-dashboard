#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 把所有 render 调用包 try/catch，确保一个失败不阻断其他。
with open('dashboard/index.html', encoding='utf-8') as f:
    s = f.read()

# 1. renderRisk()
s = s.replace('renderRisk();\n', 'try{renderRisk()}catch(e){console.error("[renderRisk fail]",e)};\n', 1)

# 2. renderSnapshots()
s = s.replace('renderSnapshots();', 'try{renderSnapshots()}catch(e){console.error("[renderSnapshots fail]",e)};')

# 3. renderScores()
s = s.replace('renderScores(); ', 'try{renderScores()}catch(e){console.error("[renderScores fail]",e)}; ', 1)
s = s.replace('renderScores();\n', 'try{renderScores()}catch(e){console.error("[renderScores fail]",e)};\n', 1)

# 4. renderScoreDetails / renderAllocCard
s = s.replace('renderScoreDetails(S);', 'try{renderScoreDetails(S)}catch(e){console.error("[renderScoreDetails fail]",e)};')
s = s.replace('renderAllocCard(S);', 'try{renderAllocCard(S)}catch(e){console.error("[renderAllocCard fail]",e)};')

# 5. renderPosition()
s = s.replace('renderPosition();\n', 'try{renderPosition()}catch(e){console.error("[renderPosition fail]",e.message||e,e.stack)};\n', 1)

# 6. renderPosAckHistory()
s = s.replace('renderPosAckHistory();\n', 'try{renderPosAckHistory()}catch(e){console.error("[renderPosAckHistory fail]",e)};\n')

# 7. renderSignals()
s = s.replace('renderSignals();\n', 'try{renderSignals()}catch(e){console.error("[renderSignals fail]",e.message||e,e.stack)};\n', 1)

# 8. K线 / 外围
s = s.replace(\"renderKline('szzs');\", \"try{renderKline('szzs')}catch(e){console.error('[renderKline fail]',e)};\")
s = s.replace(\"renderOv('ndx');\", \"try{renderOv('ndx')}catch(e){console.error('[renderOv fail]',e)};\")

# 9. ETF / 资金
for fn in ['renderMarginChart(50);', 'renderNbChart(50);', 'renderEtfChart();', 'renderTopBuy();']:
    name = fn.split('(')[0]
    new_call = 'try{' + fn[:-1] + '}catch(e){console.error("[' + name + ' fail]",e)};'
    s = s.replace(fn + '\n', new_call + '\n')

# 10. renderSources()
s = s.replace('renderSources();\n', 'try{renderSources()}catch(e){console.error("[renderSources fail]",e)};\n', 1)

# 11. news
for fn in ['renderNewsFeed();', 'renderNewsCats();']:
    name = fn.split('(')[0]
    s = s.replace(fn, 'try{' + fn[:-1] + '}catch(e){console.error("[' + name + ' fail]",e)};')

with open('dashboard/index.html', 'w', encoding='utf-8') as f:
    f.write(s)

print('OK')
# 校验
with open('dashboard/index.html', encoding='utf-8') as f:
    s2 = f.read()
print('braces:', s2.count('{'), '/', s2.count('}'))
print('parens:', s2.count('('), '/', s2.count(')'))
print('try{', s2.count('try{'))
print('catch(e)', s2.count('catch(e)'))
