from ..Config import config
from ..ServerWatcher import server_watcher
from ..Managers import server_manager, data_manager
from ..Utils import send_synchronous_message

import asyncio
from json import dumps, loads

from nonebot import get_driver
from nonebot.log import logger
from nonebot.exception import WebSocketClosed
from nonebot.drivers import WebSocketServerSetup, WebSocket, ASGIMixin, URL


async def verify(websocket: WebSocket):
    logger.info('检测到 WebSocket 链接，正在验证身份……')
    data = loads(await websocket.receive())
    if data.get('token') != config.token and data.get('name'):
        await websocket.send({'success': False})
        await websocket.close()
        logger.warning('身份验证失败！请检查插件配置文件是否正确。')
        return None
    await websocket.send(dumps({'success': True}))
    logger.success(F'身份验证成功，服务器 [{(name := data["name"])}] 已连接到！连接已建立。')
    return name


async def handle_websocket_minecraft(websocket: WebSocket):
    await websocket.accept()
    if name := await verify(websocket):
        data_manager.append_server(name)
        server_manager.append_server(name, websocket)
        await websocket.receive()
        while not websocket.closed:
            await asyncio.sleep(30)
        logger.info(F'检测到连接 [{name}] 已断开！')
        

async def handle_websocket_bot(websocket: WebSocket):
    await websocket.accept()
    if name := await verify(websocket):
        try:
            while True:
                response = None
                receive_message = loads(await websocket.receive())
                logger.debug(F'收到来数据 {receive_message} 。')
                data = receive_message.get('data')
                type = receive_message.get('type')
                if type == 'message':
                    response = await message(name, data)
                elif type == 'server_pid':
                    response = await server_pid(name, data)
                elif type == 'server_startup':
                    response = await server_startup(name, data)
                elif type == 'server_shutdown':
                    response = await server_shutdown(name, data)
                elif type == 'player_info':
                    response = await player_info(name, data)
                elif type == 'player_joined':
                    response = await player_joined(name, data)
                elif type == 'player_left':
                    response = await player_left(name, data)
                if response is not None:
                    await websocket.send(dumps({'success': True, 'data': response}))
                    continue
                logger.warning(F'收到来自 [{name}] 无法解析的数据 {message}')
                await websocket.send(dumps({'success': False}))
        except (ConnectionError, WebSocketClosed):
            logger.info('WebSocket 连接已关闭！')


async def message(name: str, data: dict):
    if message := data.get('message'):
        logger.debug(F'发送消息 {message} 到消息群！')
        if await send_synchronous_message(message):
            return {}
    logger.warning('发送消息失败！请检查机器人状态是否正确和群号是否填写正确。')
    return {}


async def server_pid(name: str, data: dict):
    pid = data.get('pid')
    server_watcher.append_server(name, pid)
    return {}


async def server_startup(name: str, data: dict):
    logger.info('收到服务器开启数据！尝试连接到服务器……')
    pid = data.get('pid')
    data_manager.append_server(name)
    server_watcher.append_server(name, pid)
    if config.broadcast_server:
        server_manager.broadcast(name, message='服务器已开启！', except_server=name)
        if await send_synchronous_message(F'服务器 [{name}] 已开启，喵～'):
            return {'flag': config.sync_all_game_message}
        logger.warning('发送消息失败！请检查机器人状态是否正确和群号是否填写正确。')
        return None
    return {'flag': config.sync_all_game_message}


async def server_shutdown(name: str, data: dict):
    logger.info('收到服务器关闭信息！正在断开连接……')
    name = data.get('name')
    server_watcher.remove_server(name)
    server_manager.disconnect_server(name)
    if config.broadcast_server:
        server_manager.broadcast(name, message='服务器已关闭！', except_server=name)
        if await send_synchronous_message(F'服务器 [{name}] 已关闭，呜……'):
            return {}
        logger.warning('发送消息失败！请检查机器人状态是否正确和群号是否填写正确。')
        return None
    await {}


async def player_info(name: str, data: dict):
    name = data.get('name')
    player = data.get('player')
    message = data.get('message')
    logger.debug(F'收到玩家 {player} 在服务器 [{name}] 发送消息！')
    if config.sync_all_game_message:
        if not (await send_synchronous_message(F'[{name}] <{player}> {message}')):
            logger.warning('发送消息失败！请检查机器人状态是否正确和群号是否填写正确。')
    if config.sync_message_between_servers:
        server_manager.broadcast(name, player, message, except_server=name)
    return {}


async def player_joined(name: str, data: dict):
    logger.info('收到玩家加入服务器通知！')
    player = data.get('player')
    if config.broadcast_player:
        server_message = F'玩家 {player} 加入了游戏。'
        message = F'玩家 {player} 加入了 [{name}] 服务器，喵～'
        if config.bot_prefix and player.upper().startswith(config.bot_prefix):
            message = F'机器人 {player} 加入了 [{name}] 服务器。'
            if config.sync_message_between_servers:
                server_message = F'机器人 {player} 加入了游戏。'
        if config.sync_message_between_servers:
            server_manager.broadcast(name, message=server_message, except_server=name)
        if await send_synchronous_message(message):
            return {}
        logger.warning('发送消息失败！请检查机器人状态是否正确和群号是否填写正确。')
        return None
    return {}


async def player_left(name: str, message: dict):
    logger.info('收到玩家离开服务器通知！')
    player = message.get('player')
    if config.broadcast_player:
        server_message = F'玩家 {player} 离开了游戏。'
        message = F'玩家 {player} 离开了 [{name}] 服务器，呜……'
        if config.bot_prefix and player.upper().startswith(config.bot_prefix):
            server_message = F'机器人 {player} 离开了游戏。'
            message = F'机器人 {player} 离开了 [{name}] 服务器。'
        if config.sync_message_between_servers:
            server_manager.broadcast(name, message=server_message, except_server=name)
        if await send_synchronous_message(message):
            return {}
        logger.warning('发送消息失败！请检查机器人状态是否正确和群号是否填写正确。')
        return None
    return {}


def setup_websocket_server():
    if isinstance((driver := get_driver()), ASGIMixin):
        driver.setup_websocket_server(WebSocketServerSetup(URL('/websocket/bot'), 'websocket_bot', handle_websocket_bot))
        driver.setup_websocket_server(WebSocketServerSetup(URL('/websocket/minecraft'), 'websocket_minecraft', handle_websocket_minecraft))
        logger.success('装载 WebSocket 服务器成功！')
        return None
    logger.error('装载 WebSocket 服务器失败！请检查驱动是否正确。')
    exit(1)