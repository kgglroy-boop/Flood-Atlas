"""Read-only teaching analysis HTTP routes."""
import logging
from typing import Annotated

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError

from app.analysis_models import AnalysisSummary, BuildingFeatureCollection
from app.analysis_params import parse_analysis_query, AnalysisQueryInvalid
from app.analysis_store import read_summary, read_buildings, AnalysisDataUnavailable, AnalysisStepNotFound
from app.database import open_database

router=APIRouter(prefix='/api/v1/analysis',tags=['teaching analysis'])
logger=logging.getLogger('urban_flood.analysis')


def _serve(request: Request, buildings: bool):
    try:
        step_id, limit=parse_analysis_query(list(request.query_params.multi_items()),allow_limit=buildings)
        with open_database() as connection:
            result=read_buildings(connection,step_id,limit) if buildings else read_summary(connection,step_id)
            model=BuildingFeatureCollection if buildings else AnalysisSummary
            return model.model_validate(result)
    except AnalysisQueryInvalid:
        raise HTTPException(422,'invalid analysis parameters') from None
    except AnalysisStepNotFound:
        raise HTTPException(404,'step not found') from None
    except (AnalysisDataUnavailable,ValidationError):
        logger.warning('Analysis data validation failed')
        raise HTTPException(503,'analysis data unavailable') from None
    except psycopg.Error:
        logger.warning('Analysis database query failed')
        raise HTTPException(503,'database unavailable') from None


@router.get('/summary',response_model=AnalysisSummary,
 description='教学合成数据。建筑相交包含边界接触；面积单位m²，道路仅计线状交集长度（m）。')
def summary(request:Request,step_id:Annotated[str,Query(description='受控步骤ID，例如S01_T30；必填且区分大小写')]):
    return _serve(request,False)


@router.get('/buildings',response_model=BuildingFeatureCollection,
 description='完整建筑Polygon（经度/纬度）；affected包含边界接触。limit不影响全量汇总，metadata明确截断。')
def buildings(request:Request,step_id:Annotated[str,Query(description='受控步骤ID，例如S01_T30；必填且区分大小写')],
              limit:Annotated[str,Query(description='十进制整数1—500；默认200，限制返回数量，不影响汇总')]='200'):
    return _serve(request,True)
