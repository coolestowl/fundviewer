import asyncio
import datetime
import os
import signal
import pickle
import uuid
import sys
import traceback
from typing import Annotated, Any, Optional
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
import uvicorn
from aakshare import get_fund_share
from config import settings
import logging

from data import (
    CACHE_PERIOD_DAY_1,
    get_fund_hold_bond,
    get_fund_hold_stack,
    get_fund_info,
    get_fund_info_xq,
    get_fund_rate,
    get_index,
    get_index_new,
    get_rt_evaluation,
    get_rt_factor,
)


app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None, openapi_url=None)
app.state.favour = {}
app.state.share = {}

GUEST_ACOUNT = "guest"

templates = Jinja2Templates(directory="templates")


@pass_context
def urlx_for(
    context: dict,
    name: str,
    **path_params: Any,
) -> str:
    request: Request = context["request"]
    http_url = request.url_for(name, **path_params)
    if "https" in settings.base_url:
        return http_url.replace(scheme="https")
    return http_url


templates.env.globals["url_for"] = urlx_for


basic_auth = HTTPBasic()


async def basic_authorization(
    credentials: Annotated[HTTPBasicCredentials, Depends(basic_auth)], request: Request
) -> str:
    username = credentials.username
    password = credentials.password

    auth_users = settings.users.split(",")
    for user in auth_users:
        try:
            tmp = user.split(":")
            a_u = tmp[0]
            a_p = tmp[1]

            if a_u == username and a_p == password:
                return username
        except:
            continue
    logging.error(
        f"Login failed. IP: {request.client.host} Username: {credentials.username}"
    )
    raise HTTPException(status_code=401, detail="Unauthorized token")


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/docs", dependencies=[Depends(basic_authorization)])
async def get_documentation():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


@app.get("/openapi.json", dependencies=[Depends(basic_authorization)])
async def openapi():
    return get_openapi(title=settings.app_name, version="0.1.0", routes=app.routes)


@app.get("/api/v1/index", dependencies=[Depends(basic_authorization)])
async def api_index(request: Request):
    """获取当前指数动态"""
    try:
        now, index = await get_index()
    except Exception as e:
        logging.error(f"get index error: {e}")
        raise HTTPException(400, detail=f"get index error: {e}")

    return {"time": now, "index": index}


@app.get("/api/v1/fund_info/{code}", dependencies=[Depends(basic_authorization)])
async def api_fund_info(code: str, request: Request):
    """获取基金基本信息"""
    try:
        fund_info = await get_fund_info(code)
    except Exception as e:
        traceback.print_exc()
        logging.error(f"get fund info error: {e}")
        raise HTTPException(400, detail=f"get fund info error: {e}")

    return fund_info


@app.get("/api/v1/realtime", dependencies=[Depends(basic_authorization)])
async def api_rt(request: Request):
    """获取股票/债券实时价格"""
    try:
        now, a_stocks, h_stocks, m_stocks, bond_index = await get_rt_factor()
    except Exception as e:
        traceback.print_exc()
        logging.error(f"get real time price error: {e}")
        raise HTTPException(400, detail=f"get real time price error: {e}")
    print(a_stocks, h_stocks, m_stocks, bond_index)
    return {
        "time": now,
        "a_stocks": len(a_stocks),
        "h_stocks": len(h_stocks),
        "m_stocks": len(m_stocks),
        "bond_index": bond_index,
    }


@app.get("/api/v1/evaluate/{code}", dependencies=[Depends(basic_authorization)])
async def api_fund_evaluate(code: str, request: Request):
    """获取基金估值"""
    try:
        now, fund_info, evaluate, _ = await get_rt_evaluation(code=code)
    except Exception as e:
        traceback.print_exc()
        logging.error(f"get real time price error: {e}")
        raise HTTPException(400, detail=f"get real time price error: {e}")

    ret = {
        "time": now,
        "code": fund_info["基金代码"],
        "name": fund_info["基金名称"],
        "evaluate": evaluate,
    }
    return ret


@app.get("/api/v1/share/{code}")
async def api_fund_share(
    code: str, request: Request, username: str = Depends(basic_authorization)
):
    """获取基金估值"""
    now = datetime.datetime.now()
    next_day = now + datetime.timedelta(days=1)

    uuid_str = str(uuid.uuid4())
    app.state.share[uuid_str] = {"code": code, "ddl": next_day}

    ret_msg = f"分享链接为 {settings.base_url}/share/{uuid_str} ,有效期为 24 小时。"
    response = await index(request, username, ret_msg, None)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    username: str = Depends(basic_authorization),
    succ_msg: Optional[str] = None,
    fail_msg: Optional[str] = None,
):
    """主页"""
    try:
        now, index = await get_index_new()
    except Exception as e:
        traceback.print_exc()
        logging.error(f"get index error: {e}")
        raise HTTPException(400, detail="get index error")

    if username not in app.state.favour:
        app.state.favour[username] = settings.favour_init.copy()

    favour_list = app.state.favour[username]

    sem = asyncio.Semaphore(5)

    async def get_fund_evaluate(code):
        async with sem:
            try:
                now, fund_info, evaluate, _ = await get_rt_evaluation(code=code)
            except Exception as e:
                traceback.print_exc()
                logging.error(f"get fund evaluation error: {e}")
                return None
            fund_info["基金估值"] = evaluate
            fund_info["估值时间"] = now.strftime("%H:%M:%S")
            return fund_info

    tasks = [get_fund_evaluate(code) for code in favour_list]

    favour_funds_info_list = await asyncio.gather(*tasks)
    favour_funds_info_list = [f for f in favour_funds_info_list if f is not None]
    now_str = now.strftime("%H:%M:%S")

    context = {
        "index_now": now_str,
        "index": index,
        "favour_funds": favour_funds_info_list,
    }

    if succ_msg is not None:
        context["alert"] = {"type": "success", "content": succ_msg}
    if fail_msg is not None:
        context["alert"] = {"type": "danger", "content": fail_msg}

    return templates.TemplateResponse(
        request=request, name="index.html", context=context
    )


@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request, username: str = Depends(basic_authorization)):
    """退出用户登陆"""
    logging.info(f"logout success. user: {username} from {request.client.host}")

    return templates.TemplateResponse(
        request=request, name="logout.html", status_code=401
    )


@app.get("/fund/{code}", response_class=HTMLResponse)
async def fund_info(
    request: Request, code: Optional[str], username: str = Depends(basic_authorization)
):
    """处理基金请求"""
    if code is None:
        response = await index(request, username, None, "基金代码为空")
        return response

    if len(code) != 6 or not code.isdigit():
        response = await index(request, username, None, "基金代码格式错误")
        return response

    try:
        now, fund_info, evaluate, detailed_price = await get_rt_evaluation(code=code)
    except Exception as e:
        logging.error(f"get fund evaluation error: {e}")
        response = await index(
            request, username, None, f"获取基金{code}估值失败，请稍后重试"
        )
        return response

    rank_list = []
    score_list = []
    try:
        for key, value in fund_info["基金评级"].items():
            rank_list.append({"评级机构": key, "评级分数": value})
            score_list.append(value)
    except Exception as e:
        logging.error(f"get fund rank error: {e}")

    for key in [
        "日增长率",
        "月增长率",
        "三月增长率",
        "六月增长率",
        "年增长率",
        "三年增长率",
    ]:
        f = fund_info["历史业绩"][key]
        try:
            int_f = float(f) if f != "N/A" and f != None else 0
        except Exception as e:
            int_f = 0
        fund_info["历史业绩"][key] = int_f

    try:
        if len(fund_info["持有股票"]) > 0:
            stock_season = fund_info["持有股票"][0]["season"]
            stock_show_total = sum([f["share"] for f in fund_info["持有股票"]])
        else:
            stock_season = None
            stock_show_total = 0
    except Exception as e:
        logging.error(f"get fund stock error: {e}")
        stock_season = None
        stock_show_total = 0

    try:
        if len(fund_info["持有债券"]) > 0:
            bond_season = fund_info["持有债券"][0]["season"]
            bond_show_total = sum([f["share"] for f in fund_info["持有债券"]])
        else:
            bond_season = None
            bond_show_total = 0
    except Exception as e:
        logging.error(f"get fund bond error: {e}")
        bond_season = None
        bond_show_total = 0

    avg_score = sum(score_list) / len(score_list) if len(score_list) > 0 else "N/A"
    now_str = now.strftime("%H:%M:%S")

    try:
        favour = 0
        if (
            username in app.state.favour
            and code in app.state.favour[username]
            and username != GUEST_ACOUNT
        ):
            favour = 2
        elif username != GUEST_ACOUNT:
            favour = 1
    except Exception as e:
        logging.error(f"get fund favour error: {e}")
        favour = 0

    return templates.TemplateResponse(
        request=request,
        name="fund.html",
        context={
            "fund": fund_info,
            "evaluate": evaluate,
            "now": now_str,
            "avg_score": avg_score,
            "rank_list": rank_list,
            "stock_season": stock_season,
            "bond_season": bond_season,
            "stock_show_total": stock_show_total,
            "bond_show_total": bond_show_total,
            "detailed_price": detailed_price,
            "favour": favour,
        },
    )


@app.get("/share/{uuid}")
async def fund_share(uuid: str, request: Request):
    """获取基金估值"""
    now = datetime.datetime.now()

    try:
        if uuid not in app.state.share:
            return HTMLResponse("分享链接已失效", status_code=200)
        ddl: datetime = app.state.share[uuid]["ddl"]
        code = app.state.share[uuid]["code"]

        if ddl < now:
            return HTMLResponse("分享链接已失效", status_code=200)
    except Exception as e:
        logging.error(f"get share link error {e}")
        return HTMLResponse("分享链接已失效", status_code=200)

    response = await fund_info(request, code, GUEST_ACOUNT)
    return response


@app.post("/fund", response_class=HTMLResponse)
async def fund_info_post(
    request: Request,
    code: Optional[str] = Form(default=None),
    username: str = Depends(basic_authorization),
):
    """处理基金请求"""
    if code is None:
        response = await index(request, username, None, "基金代码为空")
        return response
    response = await fund_info(request, code, username)
    return response


@app.get("/watch/add/{code}")
async def watch_add(
    request: Request, code: str, username: str = Depends(basic_authorization)
):
    if username not in app.state.favour:
        app.state.favour[username] = settings.favour_init.copy()
    if code not in app.state.favour[username]:
        if len(app.state.favour[username]) >= settings.max_favour:
            logging.info(f"add favour fund failed for {username}: {code}")
            response = await index(
                request, username, None, f"最多只能关注 {settings.max_favour} 个基金"
            )
            return response
        logging.info(f"add favour fund {username}: {code}")
        app.state.favour[username].append(code)

    response = RedirectResponse(url=f"/fund/{code}")
    return response


@app.get("/watch/del/{code}")
async def watch_del(
    request: Request,
    code: str,
    goback: Optional[str] = None,
    username: str = Depends(basic_authorization),
):
    if username not in app.state.favour:
        app.state.favour[username] = settings.favour_init.copy()
    if code in app.state.favour[username]:
        logging.info(f"delete favour fund for {username}: {code}")
        app.state.favour[username].remove(code)
    else:
        logging.info(f"delete favour fund failed for {username}: {code}")
        response = await index(request, username, None, "未关注该基金")
        return response

    if goback is None:
        goback = "/"

    response = RedirectResponse(url=goback)
    return response


async def daily_refresh():
    await asyncio.sleep(15)
    logging.info("enable daily update")
    while True:
        now = datetime.datetime.now()
        today = now.strftime("%Y-%m-%d %H:%M:%S")
        logging.info(f"daily update for {today}")

        try:
            fund_list = []
            for username in app.state.favour:
                for code in app.state.favour[username]:
                    if code not in fund_list:
                        fund_list.append(code)

            sem = asyncio.Semaphore(5)

            async def update_one(code: str):
                async with sem:
                    try:
                        future_basic = get_fund_info_xq(code=code)
                        future_rate = get_fund_rate(code)
                        future_hold_stock = get_fund_hold_stack(code)
                        future_hold_bond = get_fund_hold_bond(code)
                        future_share = get_fund_share(code)

                        await asyncio.gather(
                            future_basic,
                            future_rate,
                            future_hold_stock,
                            future_hold_bond,
                            future_share,
                        )
                        logging.info(f"pre-reload success for fund {code}")
                    except Exception as e:
                        logging.error(f"pre-reload failed for fund {code}: {e}")

            tasks = [update_one(code) for code in fund_list]
            await asyncio.gather(*tasks)
        except Exception as e:
            logging.error(f"daily update error: {e}")

        try:
            next = now + datetime.timedelta(days=1)
            next = next.replace(hour=22, minute=59, second=59)
            diff_sec = (next - now).total_seconds()
        except Exception as e:
            logging.error(f"daily update error: {e}")
            diff_sec = CACHE_PERIOD_DAY_1
        logging.info(f"daily update finished, next update: {next}")
        await asyncio.sleep(diff_sec)


async def auto_store():
    if settings.state_db != "":
        await asyncio.sleep(30)
        logging.info("enable auto store")
        while True:
            logging.info(f"save state to {settings.state_db}")
            try:
                with open(settings.state_db, "wb") as f:
                    state = {
                        "favour": app.state.favour,
                        "share": app.state.share,
                    }
                    pickle.dump(state, f)
            except Exception as e:
                logging.error(f"save state error: {e}")
            await asyncio.sleep(10)


def init_state():
    for up in settings.users.split(","):
        try:
            u, _ = up.split(":")
            app.state.favour[u] = settings.favour_init.copy()
        except:
            logging.error(f"Invalid user format: {up}")
            sys.exit(1)

    if settings.state_db != "" and os.path.exists(settings.state_db):
        with open(settings.state_db, "rb") as f:
            state = pickle.load(f)
            app.state.favour = state["favour"]
            app.state.share = state["share"]
        logging.info(f"load state from {settings.state_db}")


if __name__ == "__main__":

    def exit_handler(sig, frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, exit_handler)
    signal.signal(signal.SIGTERM, exit_handler)

    logging.basicConfig(
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    cwd = os.getcwd()

    init_state()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    config = uvicorn.Config(
        app=app,
        host=settings.host,
        port=settings.port,
        reload=True,
        loop=loop,
        reload_dirs=[cwd],
        reload_delay=3,
        forwarded_allow_ips="*",
    )
    server = uvicorn.Server(config=config)

    srv_f = server.serve()
    update_f = daily_refresh()
    store_f = auto_store()

    loop.run_until_complete(asyncio.gather(srv_f, update_f, store_f))
