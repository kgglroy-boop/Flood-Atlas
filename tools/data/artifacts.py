"""Versioned artifact generation; only successful bundles publish latest."""

import csv
import hashlib
import io
import os
import uuid
from pathlib import Path

import numpy as np
from osgeo import gdal

from .contract import load_contract
from .generation import build_assets, build_depths, wet_mask
from .integrity import atomic_json, canonical, file_sha, read_json, safe_child
from .raster import write_depth, polygonize_wet
from .vector import write_geopackage, read_geopackage, transport_rows
from .validation import inspect_dataset, validate_dataset


def resolve_latest(output_root: Path) -> Path:
    pointer = read_json(Path(output_root) / 'latest.json')
    return safe_child(Path(output_root), pointer['relative_path'])


def generation_identity(contract: dict) -> tuple[str, dict]:
    sources = {p.name: file_sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
    versions = {'gdal': gdal.VersionInfo('RELEASE_NAME'), 'numpy': np.__version__}
    from qgis.core import Qgis
    versions['qgis'] = Qgis.QGIS_VERSION
    identity = {'contract': contract, 'source_sha256': sources, 'tool_versions': versions}
    return hashlib.sha256(canonical(identity)).hexdigest()[:20], identity


def _update_sources(path: Path, directory: Path, generation_id: str, contract: dict):
    fields = ['dataset_id', 'kind', 'source', 'license', 'data_type', 'source_crs',
              'analysis_crs', 'units', 'provenance', 'status']
    existing = []
    if path.exists():
        with path.open(encoding='utf-8-sig', newline='') as stream:
            existing = [r for r in csv.DictReader(stream) if not r['dataset_id'].startswith('teaching-v1:')]
    rows = []
    identifiers = [(f'depth_{s}_T{t:02d}', 'water_depth', 'GeoTIFF', 'm')
                   for s in ('S01', 'S02') for t in (0, 30, 60)]
    identifiers += [(k, k, 'GeoPackage', 'm²' if k != 'roads' else 'm')
                    for k in ('study_area', 'buildings', 'roads', 'flood_extents')]
    for name, kind, data_type, units in identifiers:
        rows.append(dict(zip(fields, [f'teaching-v1:{name}', kind,
            '项目确定性脚本生成，无第三方输入', '项目生成，尚未声明对外许可', data_type,
            'EPSG:32650', 'EPSG:32650', units,
            f'synthetic_demo; generation_id={generation_id}', 'generated_and_validated'], strict=True)))
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(existing + rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(buffer.getvalue(), encoding='utf-8', newline='')
    os.replace(temporary, path)


def generate_dataset(contract_path: Path, output_root: Path, sources_path: Path) -> Path:
    contract = load_contract(contract_path)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'latest.json').exists():
        resolve_latest(root)  # Reject an unsafe existing pointer before any new writes.
    generation_id, identity = generation_identity(contract)
    target = safe_child(root, generation_id)
    if target.exists():
        validate_dataset(target, contract)
        _update_sources(Path(sources_path), target, generation_id, contract)
        atomic_json(root / 'latest.json', {'generation_id': generation_id, 'relative_path': generation_id})
        return target
    target.mkdir()
    (target / 'rasters').mkdir()
    assets = build_assets(contract)
    extents, steps = [], []
    for (scenario, minute), array in build_depths(contract).items():
        step_code = f'T{minute:02d}'
        name = f'depth_{scenario}_{step_code}.tif'
        raster_path = target / 'rasters' / name
        write_depth(raster_path, array, contract)
        # Polygonize persisted data, not the in-memory producer array.
        ds = gdal.Open(str(raster_path))
        persisted = ds.ReadAsArray()
        ds.Close()
        count = int(wet_mask(persisted, -9999, .1).sum())
        extents.append({'scenario_id': scenario, 'time_min': minute,
                        'wet_pixel_count': count, 'area_m2': count * 25, 'threshold_m': .1,
                        'geom': polygonize_wet(persisted, contract)})
        steps.append({'scenario_id': scenario, 'time_min': minute, 'step_code': step_code,
                      'generation_id': generation_id,
                      'raster_relative_path': f'teaching-v1/{generation_id}/rasters/{name}'})
    assets['flood_extents'] = extents
    write_geopackage(target / 'teaching.gpkg', assets)
    # OGR stores real fields as floats; export the persisted representation.
    assets = read_geopackage(target / 'teaching.gpkg')
    payload = {k: contract[k] for k in ('contract_version', 'dataset_id', 'model_type', 'analysis_srid')}
    payload.update({'generation_id': generation_id,
                    'scenarios': [{k: s[k] for k in ('scenario_id', 'name')} |
                                  {'dataset_id': 'teaching-v1', 'model_type': 'synthetic_demo'}
                                  for s in contract['scenarios']], 'steps': steps})
    payload.update({name: transport_rows(rows) for name, rows in assets.items()})
    atomic_json(target / 'import.json', payload)
    report = inspect_dataset(target, contract)
    from .project import write_qgis_project, write_atlas
    write_qgis_project(target, contract)
    write_atlas(target, report)
    atomic_json(target / 'validation-report.json', report)
    files = {p.relative_to(target).as_posix(): file_sha(p) for p in sorted(target.rglob('*')) if p.is_file()}
    manifest = {**identity, 'generation_id': generation_id, 'files': files,
                'semantic_sha256': report['semantic_sha256']}
    atomic_json(target / 'manifest.json', manifest)
    validate_dataset(target, contract)
    _update_sources(Path(sources_path), target, generation_id, contract)
    atomic_json(root / 'latest.json', {'generation_id': generation_id, 'relative_path': generation_id})
    return target
