import socket
import sys
import argparse
import binascii
from getpass import getpass
import portpicker
import asyncio
import aioconsole
from functools import partial
import os
import re

data_port = None
client_socket = None
passive_mode = False

class ClientFTPSocket:
    def __init__(self, dest_ip, dest_port):
        self.dest_ip = dest_ip
        self.dest_port = dest_port
        self.reader = None
        self.writer = None

    async def _open_connection(self):
        self.reader, self.writer = await asyncio.open_connection(self.dest_ip, self.dest_port)

    def write(self, bytes):
        self.writer.write(bytes)

    async def read(self, num):
        return await self.reader.read(num)

# class PasvNotAllowed(Exception):
#     pass

async def create_client_socket(dest_ip, dest_port):
    client_socket = ClientFTPSocket(dest_ip, dest_port)
    await client_socket._open_connection()
    return client_socket


async def handle_data_port(reader, writer, method_info):
    global client_socket
    normal_name = None
    filename = method_info.get('filename')
    method = method_info['method']

    print('\n')

    if method=='write':
        normal_name = re.split('[\\/]', filename)[-1]
        if os.path.exists(filename):
            os.remove(filename)
        with open(normal_name, 'wb') as file:
            while True:
                data = await reader.read(65355)
                if not data:
                    break
                file.write(data)
                file.flush()
    if method=='put':
        try:
            with open(filename, 'rb') as file:
                chunk_num = 4096
                while True:
                    chunk = file.read(chunk_num)
                    if not chunk:
                        break
                    writer.write(chunk)
        except FileNotFoundError:
            print('File not found')

    if method == "print":
        data = await reader.read(4096)
        print(data.decode()[:-2])

    writer.close()
    await writer.wait_closed()
    await get_data(client_socket, print_data=True)

async def open_connection_ftp(host_ip, port=21):
    global server_ip
    server_ip = host_ip
    global client_socket
    try:
        client_socket = await create_client_socket(host_ip, port)
    except ConnectionRefusedError:
        print('Не удалось подключиться')
        return None, None

    client_ip = client_socket.writer.get_extra_info('sockname')[0]

    await get_data(client_socket, print_data=True)

    username = await aioconsole.ainput('Введите имя: ')
    client_socket.write(b'USER ' + username.encode() + b'\r\n')

    await get_data(client_socket, print_data=True)

    password = getpass('Введите пароль: ')
    client_socket.write(b'PASS ' + password.encode() + b'\r\n')

    auth_state = (await get_data(client_socket, print_data=True))[:3]
    if auth_state == '230':
        client_socket.write(b'SYST\r\n')

        await get_data(client_socket, print_data=True)
        return client_socket
    else:
        client_socket.writer.close()
        await client_socket.writer.wait_closed()
        return None


async def help():
    command_list={'connect': 'Создаёт соединение с ftp-сервером\nconnect <ip> <port>',
                 'cd': 'Перемещает по дерикториям\ncd <directory>',
                 'disc': 'Разрывает соединение с ftp-сервером',
                 'dir': 'Показывает рабочую дерикторию',
                 'get': 'Загрузка файла на локальный хост\nget <filename>',
                 'ls': 'Показ файлов в рабочей дериктории\nls <directory|не обязательно>',
                 'help': 'Помощь\nhelp'
                 }
    for command_item in command_list.items():
        print(f'{command_item[1]}\n')

async def create_data_port(client_socket, method_info):
    global passive_mode, server_ip
    local_sock_ip = client_socket.writer.get_extra_info('sockname')[0]
    free_port = portpicker.pick_unused_port()
    bin_free_port = bin(free_port)[2:].rjust(16, '0')
    str_free_port = f'{int(bin_free_port[:8], 2)},{int(bin_free_port[8:], 2)}'.encode('ascii')

    if not passive_mode:
        client_socket.write(b'PORT ' + local_sock_ip.replace('.', ',').encode('ascii') + b',' + str_free_port + b'\r\n')
        await client_socket.writer.drain()
        handler = partial(handle_data_port, method_info=method_info)
        data_port = await asyncio.start_server(handler, local_sock_ip, free_port)
    else:
        print(passive_mode)
        passive_port = await get_passive_mode_port(client_socket)
        data_port = await create_client_socket(server_ip, passive_port)
        asyncio.create_task(handle_data_port(data_port.reader, data_port.writer, method_info))

    return data_port

async def ftp_console():
    global data_port
    global client_socket

    inputv = None
    create_data_port_list = {'ls', 'disc', 'get', 'cd', 'dir', 'put', 'passive'}
    action_list = {'ls':ls,
                   'connect':open_connection_ftp,
                   'disc': disconnect,
                   'get': get_file,
                   'cd': cd,
                   'dir': get_dir,
                   'help': help,
                   'exit': ftp_exit,
                   'put': put_file,
                   'passive': passive_mode_change_state}
    while True:
        inputv = await aioconsole.ainput('ANGLO.FTP> ')
        command_list = list(filter(bool,re.split(r'\s?"([\w\s/\\]*)"\s?|\s', inputv)))
        command, command_args = (command_list[0], command_list[1:]) if command_list else ['', '']
        if not command: continue
        if command in create_data_port_list:
            if client_socket:
                extra_info = client_socket.writer.get_extra_info('sockname')
                try:
                    await action_list[command](client_socket, *command_args)
                except Exception as error:
                    if hasattr(error, 'message'):
                        print(error.message)
                    else:
                        print(error)
            else:
                print('Сначала подключись к FTP-серверу!')
        else:
            if command in action_list:
                await action_list[command](*command_args)
            else:
                print('Unknown command')

async def passive_mode_change_state(client_socket):
    global passive_mode
    passive_mode = not passive_mode
    print('Passive mode ', ('on' if passive_mode else 'off'))

async def get_passive_mode_port(client_socket):
    client_socket.write(b'PASV\r\n')
    response = await get_data(client_socket, print_data=True)
    if response[:3] != '227':
        passive_mode = False
        raise Exception('Passive port not allowed')
    serv_dp_socket = re.split(r'\(|\)', response)[-2]
    port_bites = serv_dp_socket.split(',')[-2:]
    passive_port = int((bin(int(port_bites[0]))[2:].rjust(8, '0') + \
                        bin(int(port_bites[1]))[2:].rjust(8, '0')), 2)
    return passive_port



async def ftp_exit(client_socket=None):
    global data_port
    if client_socket:
        if data_port:
            data_port.close()
        client_socket.writer.close()
        await client_socket.writer.wait_closed()

    print('Bye!')
    quit()

async def get_data(ftp_socket, print_data=False):
    print('waiting for data')
    data = await ftp_socket.read(4096)
    data_str = data.replace(b'0xd0', b'').decode('utf-8')[:-2]
    if print_data:
        print(data_str)
    return data_str

async def ls(client_socket, *args):
    global data_port
    if not args:
        args = ['']
    data_port = await create_data_port(client_socket, {'method': 'print'})
    client_socket.write(b'LIST ' + args[0].encode() + b'\r\n')
    await client_socket.writer.drain()

async def disconnect(client_socket):
    client_socket.writer.close()
    await client_socket.writer.wait_closed()
    print('Disconnected')

async def cd(client_socket, *args):
    directory = ' '.join(args)
    client_socket.write(b'CWD ' + directory.encode() + b'\r\n')
    await get_data(client_socket, print_data=True)

async def get_dir(client_socket, writer):
    writer.write(b'PWD\r\n')
    await get_data(client_socket, print_data=True)
async def get_file(client_socket, filename):
    normal_name = re.split('[\\/]', filename)[-1]
    client_socket.write(b'TYPE I\r\n')
    await client_socket.writer.drain()
    await get_data(client_socket, print_data=True)

    if os.path.exists(normal_name):
        os.remove(normal_name)

    data_port = await create_data_port(client_socket, {'method': 'write', 'filename': filename})
    client_socket.write(b'RETR ' + filename.encode() + b'\r\n')
    await get_data(client_socket, print_data=True)

async def put_file(client_socket, filename, serv_filename=None):
    normal_name = re.split('[\\/]', filename)[-1]
    client_socket.write(b'TYPE I\r\n')

    data_port = await create_data_port(client_socket, {'method':'put', 'filename':filename})
    client_socket.write(b'STOR ' + (serv_filename.encode() if serv_filename else filename.encode()) + b'\r\n')

    await get_data(client_socket, print_data=True)

async def main():
    global client_socket
    parser = argparse.ArgumentParser()

    parser.add_argument('-i', type=str, help='IP сервера')
    parser.add_argument('-p', type=int, help='Порт сервера')
    parser.add_argument('-pasv', action='store_true', help='Пасивный режим')

    start_args = dict(parser.parse_args()._get_kwargs())
    if start_args['i']:
        server_ip = start_args['i']
        client_socket = await open_connection_ftp(server_ip, start_args['p'])
        if start_args['pasv']: await passive_mode_change_state(client_socket)
    ftp_console_task = asyncio.create_task(ftp_console())

    try:
        await asyncio.gather(ftp_console_task)
    except asyncio.CancelledError:
        pass

if __name__ == '__main__':
    asyncio.run(main())