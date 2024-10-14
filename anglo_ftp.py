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
import ssl

data_port = None
client_socket = None
# passive_mode = False

class BasicFTPSocket(socket.socket):
    def __init__(self):
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        self.loop = asyncio.get_event_loop()
    async def write(self, bytes):
        await self.loop.sock_sendall(self, bytes)

    async def read(self, max_bytes):
        data = await self.loop.sock_recv(self, max_bytes)
        return data

class ControlFTPSocket(BasicFTPSocket):
    def __init__(self, dest_ip, dest_port):
        super().__init__()
        self.connect((dest_ip, dest_port))
        self.setblocking(False)

class DataPortFTPSocket(BasicFTPSocket):
    async def server_handler(self, sock, method_info):
        normal_name = None
        filename = method_info.get('filename')
        method = method_info['method']
        data = None

        if method == 'write':
            normal_name = re.split('[\\/]', filename)[-1]
            with open(method_info['to_dir'] + '/' + normal_name, 'wb') as file:
                while True:
                    data = await self.loop.sock_recv(sock, 65355)
                    if not data:
                        break
                    file.write(data)
                    file.flush()
        if method == 'put':
            try:
                with open(filename, 'rb') as file:
                    chunk_num = 66543
                    while True:
                        chunk = file.read(chunk_num)
                        if not chunk:
                            break
                        sock.sendall(chunk)
            except FileNotFoundError:
                print('File not found')
                return {'state': 'successful', 'error': 'FileNotFount', 'data': None}

        if method == "print":
            data = (await self.loop.sock_recv(sock, 4096)).decode()[:-2]
            print(data)
        sock.close()
        return {'state': 'successful', 'data': data}

class DataPortClientFTPSocket(DataPortFTPSocket):
    def __init__(self, dest_ip, dest_port):
        super().__init__()
        self.connect((dest_ip, dest_port))
        self.setblocking(False)

    async def start_serving(self, method_info):
        data = await self.server_handler(self, method_info)
        return data

class DataPortServerFTPSocket(DataPortFTPSocket):
    def __init__(self, dest_ip, dest_port):
        super().__init__()
        self.bind((dest_ip, dest_port))
        self.listen(1)
        self.setblocking(False)

    async def start_serving(self, method_info):
        sock,_ = await self.loop.sock_accept(self)
        data = await self.server_handler(sock, method_info)
        return data

async def open_connection_ftp(host_ip, port=21, need_inp=True, passive_mode=False, **kwargs):
    global server_ip
    server_ip = host_ip
    global client_socket
    try:
        client_socket = ControlFTPSocket(host_ip, port)
        client_socket.passive_mode = passive_mode
    except ConnectionRefusedError:
        print('Не удалось подключиться')
        return None

    client_ip = client_socket.getsockname()[0]

    await get_data(client_socket, print_data=True)

    if need_inp:
        username = await aioconsole.ainput('Введите имя: ')
    else:
        username = kwargs['username']
    await client_socket.write(b'USER ' + username.encode() + b'\r\n')

    await get_data(client_socket, print_data=True)

    if need_inp:
        password = getpass('Введите пароль: ')
    else:
        password = kwargs['password']
    await client_socket.write(b'PASS ' + password.encode() + b'\r\n')

    auth_state = (await get_data(client_socket, print_data=True))[:3]
    if auth_state == '230':
        await client_socket.write(b'SYST\r\n')

        await get_data(client_socket, print_data=True)
        return client_socket
    else:
        client_socket.close()
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

async def create_data_port(client_socket: ControlFTPSocket):
    global server_ip

    loop = asyncio.get_event_loop()
    print(client_socket)
    local_sock_ip = client_socket.getsockname()[0]
    free_port = portpicker.pick_unused_port()
    bin_free_port = bin(free_port)[2:].rjust(16, '0')
    str_free_port = f'{int(bin_free_port[:8], 2)},{int(bin_free_port[8:], 2)}'.encode('ascii')

    if not client_socket.passive_mode:
        await client_socket.write(b'PORT ' + local_sock_ip.replace('.', ',').encode('ascii') + b',' + str_free_port + b'\r\n')
        port_response = await get_data(client_socket, print_data=True)

        data_port = DataPortServerFTPSocket(local_sock_ip, free_port)
    else:
        passive_port = await get_passive_mode_port(client_socket)
        data_port = DataPortServerFTPSocket(server_ip, passive_port)

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
                extra_info = client_socket.getsockname()[0]
                # try:
                await action_list[command](client_socket, *command_args)
                # except Exception as error:
                #     if hasattr(error, 'message'):
                #         print(error.message)
                #     else:
                #         print(error)
            else:
                print('Сначала подключись к FTP-серверу!')
        else:
            if command in action_list:
                await action_list[command](*command_args)
            else:
                print('Unknown command')

async def passive_mode_change_state(client_socket):
    client_socket.passive_mode = client_socket.passive_mode
    print('Passive mode ', ('on' if client_socket.passive_mode else 'off'))

async def get_passive_mode_port(client_socket):
    await client_socket.write(b'PASV\r\n')
    response = await get_data(client_socket, print_data=True)
    if response[:3] != '227':
        client_socket.passive_mode = False
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
        client_socket.close()

    print('Bye!')
    quit()

async def get_data(ftp_socket, print_data=False):
    data = await ftp_socket.read(4096)
    data_str = data.replace(b'0xd0', b'').decode('utf-8')[:-2]
    if print_data:
        print(data_str)
    return data_str

async def ls(client_socket, *args):
    if not args:
        args = ['']
    data_port = await create_data_port(client_socket)
    await client_socket.write(b'LIST ' + args[0].encode() + b'\r\n')
    dp_state = await get_data(client_socket, print_data=True)
    response = await data_port.start_serving({'method': 'print'})
    if response['state'] == 'successful':
        if dp_state[:3] == '150':
            await get_data(client_socket, print_data=True)
    return response

async def disconnect(client_socket):
    client_socket.close()
    print('Disconnected')

async def cd(client_socket, *args):
    directory = ' '.join(args)
    await client_socket.write(b'CWD ' + directory.encode() + b'\r\n')
    await get_data(client_socket, print_data=True)

async def get_dir(client_socket):
    await client_socket.write(b'PWD\r\n')
    await get_data(client_socket, print_data=True)
async def get_file(client_socket, filename, to_dir):
    normal_name = re.split('[\\/]', filename)[-1]
    await client_socket.write(b'TYPE I\r\n')
    type_response = await get_data(client_socket, print_data=True)
    file_path = (to_dir if to_dir != '/' else '') + '/' + filename
    if os.path.exists(file_path):
        os.remove(file_path)

    data_port = await create_data_port(client_socket)
    await client_socket.write(b'RETR ' + filename.encode() + b'\r\n')
    retr_state = await get_data(client_socket, print_data=True)
    response = await data_port.start_serving({'method': 'write', 'filename': filename, 'to_dir':to_dir})
    return response

async def put_file(client_socket, filename, serv_filename=None):
    normal_name = re.split('[\\/]', filename)[-1]
    await client_socket.write(b'TYPE I\r\n')
    await get_data(client_socket, print_data=True)

    data_port = await create_data_port(client_socket)
    await client_socket.write(b'STOR ' + (serv_filename.encode() if serv_filename else filename.encode()) + b'\r\n')
    stor_response = await get_data(client_socket, print_data=True)
    if stor_response[:3] == '550':
        return {'state':'error', 'error':'PermissionError', 'data':None}
    response = await data_port.start_serving({'method':'put', 'filename':filename})
    await get_data(client_socket, print_data=True)
    return response

async def del_file(client_socket, filepath):
    await client_socket.write(b'DELE ' + filepath.encode() + b'\r\n')
    response = await get_data(client_socket, print_data=True)
    if response[:3] == '250':
        return {'state':'successful'}
    else:
        return {'state':'error', 'error':'FileDoesNotExist'}

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