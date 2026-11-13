"""Explicit public response contracts; no internal geometry paths or credentials."""
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NonNegative = Annotated[float, Field(ge=0)]


class PublicModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class AnalysisIdentity(PublicModel):
    step_id: Literal['S01_T00','S01_T30','S01_T60','S02_T00','S02_T30','S02_T60']
    dataset_id: Literal['teaching-v1']
    generation_id: Annotated[str, Field(pattern=r'^[0-9a-f]{20}$')]
    model_type: Literal['synthetic_demo']
    analysis_srid: Literal[32650]
    threshold_m: Literal[0.1]


class AnalysisSummary(AnalysisIdentity):
    flooded_area_m2: NonNegative
    affected_buildings: Annotated[int, Field(ge=0,le=200)]
    flooded_road_length_m: NonNegative


class BuildingGeometry(PublicModel):
    type: Literal['Polygon']
    coordinates: list[list[list[float]]]

    @field_validator('coordinates')
    @classmethod
    def valid_rings(cls, rings):
        if not rings:
            raise ValueError('empty building geometry')
        for ring in rings:
            if len(ring)<4 or ring[0]!=ring[-1]:
                raise ValueError('invalid ring')
            for point in ring:
                if len(point)!=2 or not all(math.isfinite(v) for v in point) or not -180<=point[0]<=180 or not -90<=point[1]<=90:
                    raise ValueError('invalid longitude/latitude')
        return rings


class BuildingProperties(PublicModel):
    building_id: str
    name: str
    usage: Literal['demo']
    affected: bool


class BuildingFeature(PublicModel):
    type: Literal['Feature']
    id: str
    properties: BuildingProperties
    geometry: BuildingGeometry

    @model_validator(mode='after')
    def matching_id(self):
        if self.id!=self.properties.building_id:
            raise ValueError('building identity mismatch')
        return self


class BuildingMetadata(AnalysisIdentity):
    geometry_srid: Literal[4326]
    limit: Annotated[int, Field(ge=1,le=500)]
    returned_count: Annotated[int, Field(ge=0,le=200)]
    total_buildings: Literal[200]
    truncated: bool


class BuildingFeatureCollection(PublicModel):
    type: Literal['FeatureCollection']
    features: list[BuildingFeature]
    metadata: BuildingMetadata

    @model_validator(mode='after')
    def matching_counts(self):
        m=self.metadata
        ids=[f.id for f in self.features]
        if ids!=sorted(set(ids)) or len(ids)!=m.returned_count or len(ids)!=min(m.limit,m.total_buildings) or m.truncated!=(len(ids)<m.total_buildings):
            raise ValueError('building collection count mismatch')
        return self
