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
import sslkeylog
import sslpsk
import OpenSSL

sslkeylog.set_keylog(os.environ.get('SSLKEYLOGFILE'))

data_port = None
client_socket = None
port = 0
session = None

class BasicFTPSocket(socket.socket):
    def __init__(self):
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)

class ControlFTPSocket(BasicFTPSocket):
    def __init__(self, dest_ip, dest_port):
        super().__init__()
        self.connect((dest_ip, dest_port))

def start_serving(dp_sock, method_info, passive_mode):
    if passive_mode:
        dp_sock = dp_sock.context.wrap_socket(dp_sock)
        dp_sock.session = session
        data = server_handler(dp_sock, method_info)
    else:
        sock, _ = dp_sock.accept()
        sock = dp_sock.context.wrap_socket(sock)
        dp_sock.session = session
        data = server_handler(sock, method_info)
    return data

def server_handler(sock, method_info):
    normal_name = None
    filename = method_info.get('filename')
    method = method_info['method']
    data = None

    if method == 'write':
        normal_name = re.split('[\\/]', filename)[-1]
        with open(method_info['to_dir'] + '/' + normal_name, 'wb') as file:
            while True:
                data = sock.recv(65355)
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
        print('get')
        data = sock.recv(4096).decode()[:-2]
        print(data)

    sock.unwrap()
    sock.close()
    return {'state': 'successful', 'data': data}

class DataPortClientFTPSocket(socket.socket):
    def __init__(self, dest_ip, dest_port):
        super().__init__()
        self.connect((dest_ip, dest_port))

    def start_serving(self, method_info):
        data = server_handler(self, method_info)
        return data

class DataPortServerFTPSocket(socket.socket):
    def __init__(self, dest_ip, dest_port):
        super().__init__()
        self.bind((dest_ip, dest_port))
        self.listen(1)

    def start_serving(self, method_info):
        sock,_ = self.accept()
        data = server_handler(sock, method_info)
        return data

def open_connection_ftp(host_ip, port=21, need_inp=True, passive_mode=False, ssl_state=False, **kwargs):
    global server_ip
    server_ip = host_ip
    global client_socket
    try:
        if ssl_state:
            context = ssl.create_default_context()
            context.load_verify_locations('/etc/ssl/cert.pem')
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        client_socket = ControlFTPSocket(host_ip, port)
    except ConnectionRefusedError:
        print('Не удалось подключиться')
        return None

    client_ip = client_socket.getsockname()[0]

    get_data(client_socket, print_data=True)

    if ssl_state:
        client_socket.sendall(b'AUTH TLS\r\n')
        get_data(client_socket, print_data=True)
        # ssl.SSLSession
        client_socket = context.wrap_socket(client_socket)
        print(context.session_stats(), client_socket.session_reused)
        client_socket.context = context
        client_socket.is_ssl = True
        print('cid:', client_socket.session.id)
    else:
        client_socket.is_ssl = False
    client_socket.passive_mode = passive_mode

    if need_inp:
        username = input('Введите имя: ')
    else:
        username = kwargs['username']
    client_socket.sendall(b'USER ' + username.encode() + b'\r\n')

    get_data(client_socket, print_data=True)

    if need_inp:
        password = getpass('Введите пароль: ')
    else:
        password = kwargs['password']
    client_socket.sendall(b'PASS ' + password.encode() + b'\r\n')

    auth_state = (get_data(client_socket, print_data=True))[:3]
    if auth_state == '230':
        client_socket.sendall(b'SYST\r\n')

        get_data(client_socket, print_data=True)
        if ssl_state:
            client_socket.sendall(b'OPTS UTF8 ON\r\n')
            get_data(client_socket, print_data=True)
            client_socket.sendall(b'PBSZ 0\r\n')
            get_data(client_socket, print_data=True)
            client_socket.sendall(b'PROT P\r\n')
            get_data(client_socket, print_data=True)

        if client_socket.passive_mode:
            get_passive_mode_port(client_socket)
        return client_socket
    else:
        client_socket.close()
        return None


def help():
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

def create_data_port(client_socket: ControlFTPSocket, reuse=False):
    global server_ip
    global port

    local_sock_ip = client_socket.getsockname()[0]
    free_port = portpicker.pick_unused_port()
    bin_free_port = bin(free_port)[2:].rjust(16, '0')
    str_free_port = f'{int(bin_free_port[:8], 2)},{int(bin_free_port[8:], 2)}'.encode('ascii')

    if not client_socket.passive_mode:
        client_socket.sendall(b'PORT ' + local_sock_ip.replace('.', ',').encode('ascii') + b',' + str_free_port + b'\r\n')
        port_response = get_data(client_socket, print_data=True)

        if reuse:
            data_port = DataPortServerFTPSocket(local_sock_ip, port)
        else:
            data_port = DataPortServerFTPSocket(local_sock_ip, free_port)
            port = free_port
    else:
        passive_port = get_passive_mode_port(client_socket)
        data_port = DataPortClientFTPSocket(server_ip, passive_port)

    if client_socket.is_ssl:
        data_port.context = client_socket.context
        data_port.context.check_hostname = False
        data_port.context.load_verify_locations('/etc/ssl/cert.pem')
        data_port.context.verify_mode = ssl.CERT_NONE

    return data_port

def ftp_console():
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
        inputv = input('ANGLO.FTP> ')
        command_list = list(filter(bool,re.split(r'\s?"([\w\s/\\]*)"\s?|\s', inputv)))
        command, command_args = (command_list[0], command_list[1:]) if command_list else ['', '']
        if not command: continue
        if command in create_data_port_list:
            if client_socket:
                extra_info = client_socket.getsockname()[0]
                # try:
                action_list[command](client_socket, *command_args)
                # except Exception as error:
                #     if hasattr(error, 'message'):
                #         print(error.message)
                #     else:
                #         print(error)
            else:
                print('Сначала подключись к FTP-серверу!')
        else:
            if command in action_list:
                action_list[command](*command_args)
            else:
                print('Unknown command')

def passive_mode_change_state(client_socket):
    client_socket.passive_mode = client_socket.passive_mode
    print('Passive mode ', ('on' if client_socket.passive_mode else 'off'))

def get_passive_mode_port(client_socket):
    client_socket.sendall(b'PASV\r\n')
    response = get_data(client_socket, print_data=True)
    if response[:3] != '227':
        client_socket.passive_mode = False
        raise Exception('Passive port not allowed')
    serv_dp_socket = re.split(r'\(|\)', response)[-2]
    port_bites = serv_dp_socket.split(',')[-2:]
    passive_port = int((bin(int(port_bites[0]))[2:].rjust(8, '0') + \
                        bin(int(port_bites[1]))[2:].rjust(8, '0')), 2)
    return passive_port

def ftp_exit(client_socket=None):
    global data_port
    if client_socket:
        if data_port:
            data_port.close()
        client_socket.close()

    print('Bye!')
    quit()

def get_data(ftp_socket, print_data=False):
    data = ftp_socket.recv(4096)
    data_str = data.replace(b'0xd0', b'').decode('utf-8')[:-2]
    if print_data:
        print(data_str)
    return data_str

def ls(client_socket, *args):
    if not args:
        args = ['']
    data_port = create_data_port(client_socket)
    client_socket.sendall(b'LIST ' + args[0].encode() + b'\r\n')
    dp_state = get_data(client_socket, print_data=True)
    response = start_serving(data_port, {'method': 'print'}, client_socket.passive_mode)
    if response['state'] == 'successful':
        if dp_state[:3] in ('150', '522'):
            get_data(client_socket, print_data=True)
    # data_port = create_data_port(client_socket, reuse=True)
    client_socket.sendall(b'LIST ' + args[0].encode() + b'\r\n')
    dp_state = get_data(client_socket, print_data=True)
    response = start_serving(data_port, {'method': 'print'}, client_socket.passive_mode)
    if response['state'] == 'successful':
        if dp_state[:3] in ('150', '522'):
            get_data(client_socket, print_data=True)
    return response

def disconnect(client_socket):
    client_socket.close()
    print('Disconnected')

def cd(client_socket, *args):
    directory = ' '.join(args)
    client_socket.sendall(b'CWD ' + directory.encode() + b'\r\n')
    get_data(client_socket, print_data=True)

def get_dir(client_socket):
    client_socket.sendall(b'PWD\r\n')
    get_data(client_socket, print_data=True)
def get_file(client_socket, filename, to_dir='.', *args):
    normal_name = re.split('[\\/]', filename)[-1]
    client_socket.sendall(b'TYPE I\r\n')
    type_response = get_data(client_socket, print_data=True)
    file_path = (to_dir if to_dir != '/' else '') + '/' + filename
    if os.path.exists(file_path):
        os.remove(file_path)

    data_port = create_data_port(client_socket)
    client_socket.sendall(b'RETR ' + filename.encode() + b'\r\n')
    retr_state = get_data(client_socket, print_data=True)
    if retr_state[:3] in ("150", "520"):
        response = start_serving(data_port, {'method': 'write', 'filename': filename, 'to_dir':to_dir}, client_socket.passive_mode)
        get_data(client_socket, print_data=True)
        return response

def put_file(client_socket, filename, serv_filename=None):
    normal_name = re.split('[\\/]', filename)[-1]
    client_socket.sendall(b'TYPE I\r\n')
    get_data(client_socket, print_data=True)

    data_port = create_data_port(client_socket)
    client_socket.sendall(b'STOR ' + (serv_filename.encode() if serv_filename else filename.encode()) + b'\r\n')
    stor_response = get_data(client_socket, print_data=True)
    if stor_response[:3] == '550':
        return {'state':'error', 'error':'PermissionError', 'data':None}
    response = start_serving(data_port, {'method':'put', 'filename':filename}, client_socket.passive_mode)
    get_data(client_socket, print_data=True)
    return response

def del_file(client_socket, filepath):
    client_socket.sendall(b'DELE ' + filepath.encode() + b'\r\n')
    response = get_data(client_socket, print_data=True)
    if response[:3] == '250':
        return {'state':'successful'}
    else:
        return {'state':'error', 'error':'FileDoesNotExist'}

def main():
    global client_socket
    parser = argparse.ArgumentParser()

    parser.add_argument('-i', type=str, help='IP сервера')
    parser.add_argument('-p', type=int, help='Server port')
    parser.add_argument('-pasv', action='store_true', help='Passive mode')
    parser.add_argument('-ssl', action='store_true', help='SSL enable')

    start_args = dict(parser.parse_args()._get_kwargs())
    if start_args['i']:
        server_ip = start_args['i']
        client_socket = open_connection_ftp(server_ip, start_args['p'], passive_mode=start_args['pasv'], ssl_state=start_args['ssl'])
        # if start_args['pasv']: passive_mode_change_state(client_socket)

    while True:
        ftp_console()

if __name__ == '__main__':
   main()