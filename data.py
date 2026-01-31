import asyncio
import datetime
import traceback
from typing import Dict

import pandas as pd
from cache import AsyncTTL
from arcache import AsyncRefreshTTL
import aakshare as aak
import logging

CACHE_PERIOD_MIN_3 = 180
CACHE_PERIOD_HOUR_1 = 3600
CACHE_PERIOD_HOUR_2 = 7200
CACHE_PERIOD_DAY_1 = 86400
CACHE_PERIOD_DAY_15 = 86400 * 15

night_cache = {}


@AsyncTTL(time_to_live=CACHE_PERIOD_MIN_3, maxsize=1)
async def get_index():
    """获取最新的指数信息（交易时间更新）"""
    now = datetime.datetime.now()
    logging.info(f"getting index for {now}")

    if now.hour >= 15 or now.hour < 9:
        ret = night_cache.get("index", None)
        if ret is not None:
            logging.info(f"get index from long-term cache at {now}")
            return ret
    try:
        night_cache.pop("index")
    except KeyError:
        pass

    tmp_index = []
    stock_zh_index_spot_df = await aak.stock_zh_index_spot_sina()
    for code in ["sh000001", "sh000300", "sh000016", "sz399006"]:
        row = stock_zh_index_spot_df[stock_zh_index_spot_df["代码"] == code].iloc[0]
        tmp_index.append(
            {
                "name": row["名称"],
                "code": row["代码"],
                "price": row["最新价"],
                "rate": row["涨跌幅"],
            }
        )

    if now.hour >= 15 or now.hour < 9:
        night_cache["index"] = (now, tmp_index.copy())

    return now, tmp_index


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_MIN_3, maxsize=1, concurrent_lock=1)
async def get_index_new():
    """获取最新的指数信息（交易时间更新，使用东方财富版本）"""
    now = datetime.datetime.now()
    logging.info(f"getting index for {now}")

    if now.hour >= 15 or now.hour < 9:
        ret = night_cache.get("index_new", None)
        if ret is not None:
            logging.info(f"get index from long-term cache at {now}")
            return ret
    try:
        night_cache.pop("index_new")
    except KeyError:
        pass

    tmp_index = []

    sh_future = aak.stock_zh_index_spot_em("沪深重要指数")
    # sz_future = aak.stock_zh_index_spot_em("沪深重要指数")

    sh_index = await asyncio.gather(sh_future)
    all_index = sh_index[0]
    print(all_index)
    for code in ["000001", "000300", "000016", "399006", "000905", "000906"]:
        row = all_index[all_index["代码"] == code].iloc[0]
        tmp_index.append(
            {
                "name": row["名称"],
                "code": row["代码"],
                "price": row["最新价"],
                "rate": row["涨跌幅"],
                "start": row["今开"],
                "high": row["最高"],
                "low": row["最低"],
            }
        )

    if now.hour >= 15 or now.hour < 9:
        night_cache["index_new"] = (now, tmp_index.copy())

    return now, tmp_index


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_DAY_15, maxsize=1, concurrent_lock=1)
async def get_fund_rate_all(_cache_refresh: bool = False):
    """获得基金的评级信息"""
    logging.info(f"getting fund rate all")
    fund_ratio = await aak.fund_rating_all()
    return fund_ratio


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_DAY_1, maxsize=1024)
async def get_fund_rate(code: str, _cache_refresh: bool = False):
    """获得基金的评级信息"""
    logging.info(f"getting fund rate for code {code}")
    fund_ratio = await get_fund_rate_all(_cache_refresh=_cache_refresh)
    selected_fund = fund_ratio[fund_ratio.代码 == code]
    
    # Check if the fund was found in the rating database
    if selected_fund.empty:
        logging.warning(f"Fund {code} not found in rating database")
        return {}
    
    selected_fund = selected_fund.iloc[0]

    ret = {}

    for name in ["上海证券", "招商证券", "济安金信"]:
        value = selected_fund[name]
        if not value or pd.isna(value):
            continue
        ret[name] = value

    return ret


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_DAY_15, maxsize=1024)
async def get_fund_hold_stack(code: str, _cache_refresh: bool = False):
    """获得基金的持仓股票信息"""
    logging.info(f"getting fund hold stack for {code}")
    today = datetime.date.today()

    try:
        year = today.year
        ### 如何是前4个月，那么调整一下范围
        month = today.month
        if month <= 4:
            a1 = aak.fund_portfolio_hold_em(symbol=code, date=f"{year}")
            a2 = aak.fund_portfolio_hold_em(symbol=code, date=f"{year-1}")
            ret1, ret2 = await asyncio.gather(a1, a2)
            fund_portfolio_hold_em_df = pd.concat([ret1, ret2])
        else:
            fund_portfolio_hold_em_df = await aak.fund_portfolio_hold_em(
                symbol=code, date=f"{year}"
            )
        if len(fund_portfolio_hold_em_df) == 0:
            return []

        first_item = fund_portfolio_hold_em_df.iloc[0]

        season = first_item["季度"]
        fund_portfolio_hold_em_df = fund_portfolio_hold_em_df[
            fund_portfolio_hold_em_df.季度 == season
        ]

        result = []
        for _, row in fund_portfolio_hold_em_df.iterrows():
            if row["占净值比例"] <= 0:
                continue
            result.append(
                {
                    "code": row["股票代码"],
                    "name": row["股票名称"],
                    "share": row["占净值比例"],
                    "season": season,
                }
            )
    except Exception as e:
        traceback.print_exc()
        logging.error(f"get fund hold stack error: {e}")
        return []
    return result


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_DAY_15, maxsize=1024)
async def get_fund_hold_bond(code: str, _cache_refresh: bool = False):
    """获得基金的持仓债券信息"""
    logging.info(f"getting fund hold bond for {code}")
    today = datetime.date.today()
    try:
        year = today.year
        ### 如何是前4个月，那么调整一下范围
        month = today.month
        if month <= 4:
            a1 = aak.fund_portfolio_bond_hold_em(symbol=code, date=f"{year}")
            a2 = aak.fund_portfolio_bond_hold_em(symbol=code, date=f"{year-1}")
            ret1, ret2 = await asyncio.gather(a1, a2)
            fund_portfolio_bond_hold_em = pd.concat([ret1, ret2])
        else:
            fund_portfolio_bond_hold_em = await aak.fund_portfolio_bond_hold_em(
                symbol=code, date=f"{year}"
            )
        if len(fund_portfolio_bond_hold_em) == 0:
            return []

        first_item = fund_portfolio_bond_hold_em.iloc[0]

        season = first_item["季度"]
        fund_portfolio_bond_hold_em = fund_portfolio_bond_hold_em[
            fund_portfolio_bond_hold_em.季度 == season
        ]

        result = []
        for _, row in fund_portfolio_bond_hold_em.iterrows():
            if row["占净值比例"] <= 0:
                continue
            result.append(
                {
                    "code": row["债券代码"],
                    "name": row["债券名称"],
                    "share": row["占净值比例"],
                    "season": season,
                }
            )
    except Exception as e:
        traceback.print_exc()
        logging.error(f"get fund hold bond error: {e}")
        return []
    return result


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_HOUR_1, maxsize=1, concurrent_lock=1)
async def get_fund_unit_price() -> Dict[str, float]:
    """获取基金的最新单位净值信息（每天3点以后开始更新）"""
    logging.info(f"getting fund unit price")

    now = datetime.datetime.now()
    if now.hour >= 0 and now.hour < 15:
        if night_cache.get("unit_price", None) is not None:
            logging.info(f"get funds' unit price from long-term cache at {now}")
            return night_cache["unit_price"]

    try:
        night_cache.pop("unit_price")
    except KeyError:
        pass

    today = datetime.date.today()

    fund_unit_price = await aak.fund_open_fund_daily_em()
    today_key = today.strftime("%Y-%m-%d") + "-单位净值"
    if today_key not in fund_unit_price.columns:
        return {}

    fund_unit_price = fund_unit_price[["基金代码", today_key, "日增长率"]]

    unit_price_dict = {}
    for _, row in fund_unit_price.iterrows():
        code = row["基金代码"]
        price = row[today_key]
        rate = row["日增长率"]
        if price == "" or rate == "":
            continue
        try:
            price = float(price)
            rate = float(rate)
            unit_price_dict[code] = {"price": price, "rate": rate}
        except Exception:
            continue

    if now.hour >= 0 and now.hour < 15:
        night_cache["unit_price"] = unit_price_dict.copy()

    return unit_price_dict


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_DAY_15, maxsize=1024)
async def get_fund_share_cache(code: str, _cache_refresh: bool = False):
    """获取基金的持有股票和债券占比信息（15天更新）"""
    ret = await aak.get_fund_share(code)
    return ret


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_DAY_1, maxsize=1024)
async def get_fund_info_fallback(code: str, _cache_refresh: bool = False):
    """获取基金的基本信息（来源东方财富，每天更新）"""
    future_purchase = aak.fund_purchase_em()
    future_rate = aak.fund_open_fund_rank_em()
    purchase_ret, rate_ret = await asyncio.gather(future_purchase, future_rate)

    # Check if the fund was found in purchase database
    purchase_fund_df = purchase_ret[purchase_ret["基金代码"] == code]
    if purchase_fund_df.empty:
        logging.error(f"Fund {code} not found in purchase database")
        raise ValueError(f"Fund {code} not found in purchase database")
    purchase_fund = purchase_fund_df.iloc[0]
    
    # Check if the fund was found in rate database
    rate_fund_df = rate_ret[rate_ret["基金代码"] == code]
    if rate_fund_df.empty:
        logging.error(f"Fund {code} not found in rate database")
        raise ValueError(f"Fund {code} not found in rate database")
    rate_fund = rate_fund_df.iloc[0]
    ret = {
        "基金代码": purchase_fund.get("基金代码", code),
        "基金名称": purchase_fund["基金简称"],
        "基金全称": purchase_fund["基金简称"],
        "基金类型": purchase_fund["基金类型"],
        "成立时间": None,
        "最新规模": None,
        "基金公司": None,
        "基金经理": None,
        "开放购买": purchase_fund["申购状态"],
        "基金评级": {},
        "历史业绩": {},
    }

    ret["单位净值"] = float(rate_fund.get("单位净值", None))
    ret["更新时间"] = rate_fund.get("日期", None)
    ret["历史业绩"]["日增长率"] = float(rate_fund.get("日增长率", None))
    ret["历史业绩"]["月增长率"] = float(rate_fund.get("近1月", None))
    ret["历史业绩"]["三月增长率"] = float(rate_fund.get("近3月", None))
    ret["历史业绩"]["六月增长率"] = float(rate_fund.get("近6月", None))
    ret["历史业绩"]["年增长率"] = float(rate_fund.get("近1年", None))
    ret["历史业绩"]["三年增长率"] = float(rate_fund.get("近3年", None))

    ret["历史业绩"]["月排名"] = None
    ret["历史业绩"]["三月排名"] = None
    ret["历史业绩"]["六月排名"] = None
    ret["历史业绩"]["年排名"] = None
    ret["历史业绩"]["三年排名"] = None
    return ret


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_DAY_1, maxsize=1024)
async def get_fund_info_xq(code: str, _cache_refresh: bool = False):
    """获取基金的基本信息（来源雪球网，每天更新）"""
    try:
        ret = await aak.fund_individual_basic_info_xq(symbol=code)
        return ret
    except Exception as e:
        return await get_fund_info_fallback(code=code, _cache_refresh=_cache_refresh)


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_HOUR_1, maxsize=1024)
async def get_fund_info(code: str, _cache_refresh: bool = False):
    """汇总获得完整的基金信息"""
    logging.info(f"getting fund info for {code}")

    future_basic = get_fund_info_xq(code=code, _cache_refresh=_cache_refresh)
    future_rate = get_fund_rate(code, _cache_refresh=_cache_refresh)
    future_hold_stock = get_fund_hold_stack(code, _cache_refresh=_cache_refresh)
    future_hold_bond = get_fund_hold_bond(code, _cache_refresh=_cache_refresh)
    future_share = get_fund_share_cache(code, _cache_refresh=_cache_refresh)
    future_recent_price = get_fund_unit_price()

    basic_ret, rate_ret, stock_ret, bond_ret, fund_share_ret, recent_price_ret = (
        await asyncio.gather(
            future_basic,
            future_rate,
            future_hold_stock,
            future_hold_bond,
            future_share,
            future_recent_price,
        )
    )

    basic_ret["基金评级"].update(rate_ret)
    basic_ret["持有股票"] = stock_ret
    basic_ret["持有债券"] = bond_ret

    # Handle case where fund_share_ret is None (API failure)
    if fund_share_ret is None:
        fund_share_ret = {}

    if (stock_share := fund_share_ret.get("stock_share", None)) is not None:
        basic_ret["持有股票占比"] = stock_share
    elif len(basic_ret["持有股票"]) > 0:
        basic_ret["持有股票占比"] = sum(
            [item["share"] for item in basic_ret["持有股票"]]
        )
    else:
        basic_ret["持有股票占比"] = 0

    if (bond_share := fund_share_ret.get("bond_share", None)) is not None:
        basic_ret["持有债券占比"] = bond_share
    elif len(basic_ret["持有债券"]) > 0:
        basic_ret["持有债券占比"] = sum(
            [item["share"] for item in basic_ret["持有债券"]]
        )
    else:
        basic_ret["持有债券占比"] = 0

    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")
    if code in recent_price_ret:
        logging.info(
            f"update recent unit price for {code}: {recent_price_ret[code]['price']} {recent_price_ret[code]['rate']}"
        )
        basic_ret["单位净值"] = recent_price_ret[code]["price"]
        basic_ret["历史业绩"]["日增长率"] = recent_price_ret[code]["rate"]
        basic_ret["更新时间"] = today_str

    return basic_ret


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_MIN_3, maxsize=1, concurrent_lock=1)
async def get_rt_factor():
    """获得实时的股票、债券信息（交易时间更新）"""
    now = datetime.datetime.now()
    logging.info(f"getting realtime price at {now}")

    if now.hour >= 15 or now.hour < 9:
        ret = night_cache.get("rt_factor", None)
        if ret is not None:
            logging.info(f"get realtime price from long-term cache at {now}")
            return ret
    try:
        night_cache.pop("rt_factor")
    except KeyError:
        pass

    future_a_stock = aak.stock_zh_a_spot_em()
    future_h_stock = aak.stock_hk_spot_em()
    future_m_stock = aak.stock_us_spot_em()
    # future_bond_normal_index = aak.bond_new_composite_index_cbond(
    #     indicator="财富", period="总值"
    # )
    future_cb_index = aak.bond_cb_index_jsl()
    future_cb = aak.bond_cov_comparison()

    (
        a_stock_ret,
        h_stock_ret,
        m_stock_ret,
        # bond_normal_index_ret,
        bond_cb_index_ret,
        bond_cb_ret,
    ) = await asyncio.gather(
        future_a_stock,
        future_h_stock,
        future_m_stock,
        # future_bond_normal_index,
        future_cb_index,
        future_cb,
    )

    a_stocks = {}
    for _, row in a_stock_ret.iterrows():
        if pd.isna(row["涨跌幅"]):
            continue
        a_stocks[row["代码"]] = row["涨跌幅"]

    h_stocks = {}
    for _, row in h_stock_ret.iterrows():
        if pd.isna(row["涨跌幅"]):
            continue
        h_stocks[row["代码"]] = row["涨跌幅"]

    m_stocks = {}
    for _, row in m_stock_ret.iterrows():
        if pd.isna(row["涨跌幅"]):
            continue
        code = row["代码"]
        if "." in code:
            code = code.split(".")[1]
        m_stocks[code] = row["涨跌幅"]

    bond_index = {}
    # start_price = bond_normal_index_ret.iloc[-2]["value"]
    # end_price = bond_normal_index_ret.iloc[-1]["value"]
    # bond_rate = (end_price / start_price - 1) * 100
    bond_index["bond"] = 0

    bond_cb_rate = bond_cb_index_ret.iloc[-1]["increase_val"] / 100
    bond_index["bond_cb"] = bond_cb_rate

    for _, row in bond_cb_ret.iterrows():
        code = row["转债代码"]
        rate = row["转债涨跌幅"]
        name = row["转债名称"]
        if pd.isna(rate):
            continue
        bond_index[code] = rate
        bond_index[name] = rate

    night_cache["rt_factor_daily"] = (
        now,
        a_stocks.copy(),
        h_stocks.copy(),
        m_stocks.copy(),
        bond_index.copy(),
    )

    if now.hour >= 15 or now.hour < 9:
        night_cache["rt_factor"] = (
            now,
            a_stocks.copy(),
            h_stocks.copy(),
            m_stocks.copy(),
            bond_index.copy(),
        )
    return now, a_stocks, h_stocks, m_stocks, bond_index


@AsyncRefreshTTL(time_to_live=CACHE_PERIOD_MIN_3, maxsize=1024)
async def get_rt_evaluation(code: str, _cache_refresh: bool = False):
    """计算基金的实时估值"""
    fund_info_future = get_fund_info(code, _cache_refresh=_cache_refresh)
    rt_factor_facture = get_rt_factor()

    fund_info, rt_factor = await asyncio.gather(fund_info_future, rt_factor_facture)
    now, a_stocks, h_stocks, m_stocks, bond_index = rt_factor

    logging.info(f"[{code}] start evaluate rate for {code} time {now}")
    stock_share_all = fund_info["持有股票占比"] / 100
    bond_share_all = fund_info["持有债券占比"] / 100

    detailed_price = {"stock": {}, "bond": {}}

    stock_share_account = 0
    stock_price_total = 0
    for stock in fund_info["持有股票"]:
        try:
            stock_code = stock["code"]
            stock_share = stock["share"] / 100

            if stock_code in a_stocks:
                stock_price = a_stocks[stock_code]
            elif stock_code in h_stocks:
                stock_price = h_stocks[stock_code]
            elif stock_code in m_stocks:
                stock_price = m_stocks[stock_code]
            else:
                continue
            logging.info(
                f"[{code}] update stock rate: {stock_code} {stock_price} {stock_share}"
            )
            detailed_price["stock"][stock_code] = stock_price
            stock_share_account += stock_share
            stock_price_total += stock_share * stock_price
        except Exception:
            traceback.print_exc()
            continue

    logging.info(f"debug point 2 {code}")

    logging.info(stock_share_account)
    stock_evaluate_rate = (
        stock_price_total / stock_share_account if stock_share_account > 0 else 0
    )
    detailed_price["stock"]["avg"] = stock_evaluate_rate
    logging.info(f"[{code}] update avg stock rate: {stock_evaluate_rate} %")

    try:
        bond_rate = bond_index["bond"]
        logging.info(f"[{code}] update avg bond rate: {bond_rate}")
        bond_cb_rate = bond_index["bond_cb"]
        logging.info(f"[{code}] update avg bond cb rate: {bond_cb_rate}")
    except Exception as e:
        logging.info(f"[{code}] update avg bond error: {e}")
        bond_rate = 0
        bond_cb_rate = 0

    bond_total = 0
    bond_price_total = 0
    for b in fund_info["持有债券"]:
        try:
            name = b["name"]
            bcode = b["code"]
            share = b["share"] / 100
            if name in bond_index:
                bond_price = bond_index[name]
            elif bcode in bond_index:
                bond_price = bond_index[bcode]
            elif "转" in name:
                bond_price = bond_cb_rate
            else:
                bond_price = bond_rate

            detailed_price["bond"][bcode] = bond_price
            logging.info(f"[{code}] update bond rate: {name} {bond_price} {share}")
            bond_total += share
            bond_price_total += share * bond_price
        except Exception:
            continue

    bond_evaluate_rate = bond_price_total / bond_total if bond_total > 0 else 0
    logging.info(f"[{code}] update avg stock rate: {bond_evaluate_rate}%")
    detailed_price["bond"]["avg"] = bond_evaluate_rate

    evaluate_rate = (
        stock_share_all * stock_evaluate_rate + bond_evaluate_rate * bond_share_all
    )
    logging.info(
        f"[{code}] update evaluated: {evaluate_rate} {stock_evaluate_rate}({stock_share_all}) {bond_evaluate_rate}({bond_share_all})"
    )
    return now, fund_info, evaluate_rate, detailed_price
