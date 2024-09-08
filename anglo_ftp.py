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
creader, cwriter = None, None
async def handle_data_port(reader, writer, method, filename=None):
    normal_name = None
    if method=='write':
        normal_name = re.split('[\\/]', filename)[-1]
        if os.path.exists(filename):
            os.remove(filename)
    while True:
        data = await reader.read(4096)
        if not data:
            break
        if method == "print":
            print(data.decode())
        if method == "write":
            with open(normal_name, 'ab') as file:
                file.write(data)

    writer.close()
    await writer.wait_closed()

async def open_connection_ftp(host_ip, port):
    global creader, cwriter
    try:
        creader, cwriter = await asyncio.open_connection(host_ip, port)
    except ConnectionRefusedError:
        print('Не удалось подключиться')
        return

    client_ip = cwriter.get_extra_info('sockname')[0]

    data = await creader.read(4096)
    print(data.decode())

    username = await aioconsole.ainput('Введите имя: ')
    cwriter.write(b'USER ' + username.encode() + b'\r\n')

    data = await creader.read(4096)
    print(data.decode())

    password = getpass('Введите пароль: ')
    cwriter.write(b'PASS ' + password.encode() + b'\r\n')

    data = await creader.read(4096)
    print(data.decode())

    cwriter.write(b'SYST\r\n')

    data = await creader.read(4096)
    print(data.decode())

    cwriter.write(b'TYPE I\r\n')

    data = await creader.read(4096)
    print(data.decode())

    return creader, cwriter

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

async def create_data_port(reader, writer, method, filename=None):
    local_sock_ip = writer.get_extra_info('sockname')[0]
    free_port = portpicker.pick_unused_port()
    bin_free_port = bin(free_port)[2:].rjust(16, '0')
    str_free_port = f'{int(bin_free_port[:8], 2)},{int(bin_free_port[8:], 2)}'.encode('ascii')
    writer.write(b'PORT ' + local_sock_ip.replace('.', ',').encode('ascii') + b',' + str_free_port + b'\r\n')
    handler = partial(handle_data_port, method=method, filename=filename)
    data_port = await asyncio.start_server(handler, local_sock_ip, free_port)

    return data_port

async def ftp_console():
    global data_port
    global creader, cwriter

    inputv = None
    create_data_port_list = {'ls', 'disc', 'get', 'cd', 'dir'}
    action_list = {'ls':ls,
                   'connect':open_connection_ftp,
                   'disc': disconnect,
                   'get': get_file,
                   'cd': cd,
                   'dir': get_dir,
                   'help': help,
                   'exit': ftp_exit,}
    while True:
        inputv = await aioconsole.ainput('ANGLO.FTP> ')
        command_list = inputv.split(' ')
        command, command_args = command_list[0], command_list[1:]
        if not command: continue
        if command in create_data_port_list:
            if creader and cwriter:
                extra_info = cwriter.get_extra_info('sockname')
                await action_list[command](creader, cwriter, *command_args)
            else:
                print('Сначала подключись к FTP-серверу!')
        else:
            if command in action_list:
                await action_list[command](*command_args)
            else:
                print('Unknown command')

async def ftp_exit(creader=None, cwriter=None):
    global data_port
    if creader and cwriter:
        if data_port:
            data_port.close()
        cwriter.close()
        await cwriter.wait_closed()

    print('Bye!')
    quit()
async def print_data(reader):
    data = await reader.read(4096)
    data_str = data.replace(b'0xd0', b'').decode('utf-8')
    print(data_str)

async def get_data(reader):
    data = await reader.read(4096)
    data_str = data.replace(b'0xd0', b'').decode('utf-8')
    print(data_str)
    return data_str

async def ls(reader, writer, *args):
    global data_port
    if not args:
        args = ['']
    data_port = await create_data_port(reader, writer, 'print')
    writer.write(b'LIST ' + args[0].encode() + b'\r\n')

    await print_data(reader)

async def disconnect(creader, cwriter):
    cwriter.close()
    await cwriter.wait_closed()
    print('Disconnected')

async def cd(reader, writer, *args):
    directory = ' '.join(args)
    writer.write(b'CWD ' + directory.encode() + b'\r\n')
    await print_data(reader)

async def get_dir(reader, writer):
    writer.write(b'PWD\r\n')
    await print_data(reader)
async def get_file(reader, writer, filename):
    normal_name = re.split('[\\/]', filename)[-1]

    if os.path.exists(normal_name):
        os.remove(normal_name)
    data_port = await create_data_port(reader, writer, 'write', filename=filename)
    writer.write(b'RETR ' + filename.encode() + b'\r\n')

    await print_data(reader)


async def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('-i', type=str, help='IP сервера')
    parser.add_argument('-p', type=int, help='Порт сервера')

    start_args = dict(parser.parse_args()._get_kwargs())
    if start_args['i']:
        server_ip = start_args['i']
        creader, cwriter = await open_connection_ftp(server_ip, start_args['p'])
    ftp_console_task = asyncio.create_task(ftp_console())

    try:
        await asyncio.gather(ftp_console_task)
    except asyncio.CancelledError:
        pass

if __name__ == '__main__':
    asyncio.run(main())