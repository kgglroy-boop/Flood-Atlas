"""Build the offline evidence page from recorded measurements, never invented metrics."""
import html
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[2]


def validate_generation(records):
    generations = {record.get('generation_id') for record in records}
    if len(generations) != 1 or None in generations:
        raise ValueError('Evidence generation mismatch')


def load_facts():
    root = ROOT / 'docs/evidence/phase7'
    gwc = json.loads((root / 'gwc/measurement.json').read_text(encoding='utf-8-sig'))
    load = json.loads((root / 'load/measurement.json').read_text(encoding='utf-8-sig'))
    reference = json.loads((root / 'load/reference.json').read_text(encoding='utf-8-sig'))
    validate_generation([gwc, load, reference])
    if any(r['status'] != 'ok' for r in [gwc, load, reference]):
        raise ValueError('Unsuccessful evidence')
    batches = load['batches']
    last = next(b for b in batches if b['vus'] == 20)
    return dict(cold=median(s['milliseconds'] for s in gwc['samples'] if s['cache'] == 'MISS'),
                hot=median(s['milliseconds'] for s in gwc['samples'] if s['cache'] == 'HIT'),
                requests=sum(b['health_requests'] + b['summary_requests'] for b in batches),
                summary_p95=last['summary']['p(95)'], health_p95=last['health']['p(95)'],
                errors=sum(b['health_error_rate'] * b['health_requests'] + b['summary_error_rate'] * b['summary_requests'] for b in batches) / sum(b['health_requests'] + b['summary_requests'] for b in batches),
                steps=reference['steps'], generation=reference['generation_id'],
                measured_at=load['captured_at'])


def render(output):
    f = load_facts()
    rows = ''.join(f'<tr><th scope="row">{html.escape(s["step_id"])}</th><td>{s["flooded_area_m2"]:,.0f}</td><td>{len(s["affected_building_ids"])}</td><td>{s["flooded_road_length_m"]:,.0f}</td></tr>' for s in f['steps'])
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Flood Atlas · 交付证据</title><style>
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f7f7f3;color:#24282c;font:16px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}a{color:#245b7c;text-underline-offset:5px}a:focus-visible{outline:3px solid #245b7c;outline-offset:4px}header,main,footer{max-width:1180px;margin:auto;padding:0 32px}header{height:88px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #dedfdb}.brand{font-weight:650;letter-spacing:-.5px;font-size:23px}.brand span{font-weight:400;font-size:12px;color:#62676d;margin-left:16px}.eyebrow{font-size:11px;letter-spacing:2px;color:#62676d}h1{font-size:clamp(36px,5vw,62px);line-height:1.22;letter-spacing:-2px;margin:18px 0 22px;font-weight:550}h2{font-size:27px;font-weight:550;letter-spacing:-.6px;margin:8px 0 20px}p{color:#62676d}.hero{padding:64px 0 32px}.hero p{max-width:620px}.cover{margin:0 0 70px;padding:12px;background:white;border:1px solid #dedfdb;border-radius:20px}img{display:block;width:100%;height:auto;border-radius:10px}figcaption{font-size:12px;color:#62676d;padding:12px 8px 4px}section{padding:38px 0;border-top:1px solid #dedfdb}.section-head{display:flex;gap:38px}.index{font-size:12px;color:#62676d;padding-top:14px;min-width:30px}.section-body{flex:1;min-width:0}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}td,th{text-align:right;border-bottom:1px solid #dedfdb;padding:15px 12px;white-space:nowrap}th:first-child{text-align:left}thead th{font-size:12px;color:#62676d;font-weight:500}tbody th{font-weight:500}.cards{display:grid;grid-template-columns:repeat(3,1fr);margin:25px 0;gap:25px}.cards>div{border-left:1px solid #dedfdb;padding-left:22px}.cards strong{font-size:36px;line-height:1.3;font-weight:550;display:block;letter-spacing:-1px}.cards small{font-size:13px;color:#62676d}.downloads{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.downloads a{padding:16px 20px;background:white;border:1px solid #dedfdb;border-radius:10px;min-height:56px;text-decoration:none}.downloads a:hover{border-color:#245b7c}.note{font-size:13px}footer{border-top:1px solid #dedfdb;padding-top:25px;padding-bottom:40px;color:#62676d;font-size:12px}@media(max-width:640px){header,main,footer{padding-left:20px;padding-right:20px}.brand span{display:none}.hero{padding-top:40px}.section-head{gap:12px}.cards{grid-template-columns:1fr;gap:24px}.downloads{grid-template-columns:1fr}h2{font-size:24px}td,th{padding:12px 8px}.cover{margin-bottom:40px}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}</style></head><body>
<header><div class="brand">∿ Flood Atlas <span>城市内涝研究</span></div><a href="#materials">交付材料 ↗</a></header><main>
<div class="hero"><div class="eyebrow">URBAN FLOOD STUDY / DELIVERY</div><h1>从情景，走向证据。</h1><p>一套可复现的城市内涝教学工作台。以统一的地图、数据与工程记录，说明每一个结果从何而来。</p><p class="note">虚构教学街区 · 预计算情景 · 本地实验 / 2026.10.20</p></div>
<figure class="cover"><img src="frontend-main.png" alt="重新设计的主地图，统计区独立于地图画布"><figcaption>01 / 情景地图 · 实际运行画面</figcaption></figure>
<section><div class="section-head"><span class="index">01</span><div class="section-body"><div class="eyebrow">DATA / SIX STEPS</div><h2>同一街区，六个观察切片。</h2><div class="table-scroll"><table><thead><tr><th>步骤</th><th>淹没面积 / m²</th><th>建筑 / 栋</th><th>道路交集 / m</th></tr></thead><tbody>ROWS</tbody></table></div><p class="note">EPSG:32650 / 5 m / depth &gt; 0.10 m。建筑相交包含触边；不等于建筑内部具有对应水深。QGIS 与数据库结果交叉核验。</p></div></div></section>
<section><div class="section-head"><span class="index">02</span><div class="section-body"><div class="eyebrow">ENGINEERING / LOCAL MEASUREMENTS</div><h2>性能判断，保留实验边界。</h2><div class="cards"><div><strong>HOT ms</strong><small>GWC 热中位 · 冷 COLD ms</small></div><div><strong>REQUESTS</strong><small>指定 k6 请求 · 错误率 ERROR</small></div><div><strong>P95 ms</strong><small>20 VU / summary p95</small></div></div><p class="note">来自已留存的阶段7实验（MEASURED），本次视觉更新未重新运行负载实验。短时本机样本不代表生产 SLA 或承载上限；GiST 小表实验未观察到稳定加速。</p></div></div></section>
<section><div class="section-head"><span class="index">03</span><div class="section-body"><div class="eyebrow">MAP MODULE / ONE SCIENTIFIC SOURCE</div><h2>表达可以替换，科学语义保持一致。</h2><p>在线 API / WMTS 与同源 SHA256 快照通过统一模块接口切换。当前 ABI 兼容 teaching-v1；更换真实城市或任意 TIFF，需要同步分析、投影与发布适配。</p><img src="final-atlas.png" alt="两个情景三个时间步的水深科学图集" loading="lazy"><p class="note">科学文件保持不变。代际 GENERATION</p><details><summary>查看独立 MVT 页面与手机布局</summary><img src="frontend-mvt.png" alt="独立建筑矢量瓦片演示" loading="lazy"><a href="frontend-mobile.png">打开手机实际视口截图 ↗</a></details></div></div></section>
<section id="materials"><div class="section-head"><span class="index">04</span><div class="section-body"><div class="eyebrow">DELIVERY / REVIEW</div><h2>带走完整的过程与结果。</h2><div class="downloads"><a href="project-report.pdf">项目报告 ↗</a><a href="engineering-report.pdf">安全与性能报告 ↗</a><a href="demo.mp4">系统演示 ↗</a><a href="architecture.md">架构与缓存策略 ↗</a><a href="manual-review.md">人工审查记录 ↗</a><a href="assessment-matrix.md">考核要求对照 ↗</a><a href="source.zip">源码归档 ↗</a><a href="teaching-data.zip">教学数据包 ↗</a></div><p class="note">预计算切换不等于实时态势；Compose 不等于已验证的云原生弹性。个人信息与人工工程审查记录由负责人按实际完成情况补充，不生成虚构签字。</p></div></div></section></main><footer>FLOOD ATLAS / 证据详见源码 docs/evidence · release-manifest.json 记录源码提交 · SHA256SUMS.txt 校验交付完整性</footer></body></html>'''
    replacements = {'ROWS': rows, 'HOT': f'{f["hot"]:.2f}', 'COLD': f'{f["cold"]:.2f}', 'REQUESTS': str(f['requests']), 'ERROR': f'{f["errors"]:.0%}', 'P95': f'{f["summary_p95"]:.2f}', 'MEASURED': html.escape(f['measured_at']), 'GENERATION': html.escape(f['generation'])}
    for key, value in replacements.items():
        page = page.replace(key, value)
    (output / 'evidence.html').write_text(page, encoding='utf-8')
    return f
