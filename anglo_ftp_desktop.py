import getpass
import sys
import PySide6
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtWidgets import QApplication, QTreeWidgetItem, QTreeWidget
import PySide6.QtAsyncio as QtAsyncio
import os
from anglo_ftp import open_connection_ftp, ls, get_file, put_file, cd, del_file
import qasync
import re

import asyncio

print(PySide6.__version__)

class AngloFTPWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('AngloFTP')
        self.layout = QtWidgets.QVBoxLayout(self)
        self.wwf_group = self.create_work_file_group() # work with file group
        self.fc_group = self.create_ftp_connection_group() # ftp connection group
        self.connection_indicator = QtWidgets.QLabel()
        self.error_indicator = QtWidgets.QLabel()
        self.error_indicator.setHidden(True)
        self.layout.addWidget(self.fc_group, alignment=QtCore.Qt.AlignTop)
        self.layout.addWidget(self.connection_indicator, alignment=QtCore.Qt.AlignTop)
        self.layout.addWidget(self.error_indicator, alignment=QtCore.Qt.AlignTop)
        self.layout.addWidget(self.wwf_group, alignment=QtCore.Qt.AlignBottom)

    def create_ftp_connection_group(self):
        wid = QtWidgets.QGroupBox()
        wid.layout = QtWidgets.QHBoxLayout(wid)
        server_edit_label = QtWidgets.QLabel(text='Server IP:')
        user_data_label = QtWidgets.QLabel(text='Username/Password:')
        self.server_ip_edit = QtWidgets.QLineEdit()
        self.server_port_edit = QtWidgets.QLineEdit()
        self.username_edit = QtWidgets.QLineEdit()
        self.password_edit = QtWidgets.QLineEdit()
        pasv_mod_checkbox = QtWidgets.QLabel('Passive mode')
        self.pasv_mod_checkbox = QtWidgets.QCheckBox()
        connect_button = QtWidgets.QPushButton('Connect')
        self.server_ip_edit.setMaximumSize(200, 30)
        self.server_port_edit.setMaximumSize(50, 30)
        self.username_edit.setMaximumSize(200, 30)
        self.password_edit.setMaximumSize(200, 30)
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        connect_button.clicked.connect(self.ftp_connect)
        wid.layout.addWidget(server_edit_label, alignment=QtCore.Qt.AlignLeft)
        wid.layout.addWidget(self.server_ip_edit, alignment=QtCore.Qt.AlignLeft)
        wid.layout.addWidget(self.server_port_edit, alignment=QtCore.Qt.AlignLeft)
        wid.layout.addWidget(user_data_label, alignment=QtCore.Qt.AlignLeft)
        wid.layout.addWidget(self.username_edit, alignment=QtCore.Qt.AlignLeft)
        wid.layout.addWidget(self.password_edit, alignment=QtCore.Qt.AlignLeft)
        wid.layout.addWidget(pasv_mod_checkbox, alignment=QtCore.Qt.AlignLeft)
        wid.layout.addWidget(self.pasv_mod_checkbox, alignment=QtCore.Qt.AlignLeft)
        wid.layout.addWidget(connect_button)
        wid.layout.addStretch()
        return wid

    def create_work_file_group(self):
        wid = QtWidgets.QGroupBox()
        wid.local_tree = QTreeWidget()
        wid.server_tree = QTreeWidget()
        wid.local_tree.setHeaderLabel('Local files')
        wid.server_tree.setHeaderLabel('Server files')
        local_root_dir_item = QtWidgets.QTreeWidgetItem(['/'])
        local_root_dir_item.file_path = '/'
        local_root_dir_item.file_type = 'd'
        local_root_dir_item.files_added = False
        local_root_dir_item.setIcon(0, QtGui.QIcon('img/folder.png'))
        local_root_dir_item.addChildren(self.fill_out_local_item('/'))
        wwf_box = QtWidgets.QGroupBox() #working with file box
        wwf_box.layout = QtWidgets.QVBoxLayout(wwf_box)
        wid.local_tree.addTopLevelItem(local_root_dir_item)
        wid.local_tree.itemExpanded.connect(self.get_local_directory_files)
        wid.local_tree.itemSelectionChanged.connect(self.change_button_enable_state)
        local_root_dir_item.setExpanded(True)
        local_root_dir_item.setSelected(True)
        wid.server_tree.itemExpanded.connect(self.get_server_directory_files)
        wid.server_tree.itemClicked.connect(self.server_item_click_trigger)
        wid.layout = QtWidgets.QHBoxLayout(wid)
        wid.layout.addWidget(wid.local_tree, alignment=QtCore.Qt.AlignLeft)
        self.get_file_button = QtWidgets.QPushButton('Get file')
        self.get_file_button.clicked.connect(self.get_file)
        self.get_file_button.setEnabled(False)
        self.put_file_button = QtWidgets.QPushButton('Put file')
        self.put_file_button.clicked.connect(self.put_file)
        self.del_file_button = QtWidgets.QPushButton('Delete file')
        self.del_file_button.clicked.connect(self.del_file)
        self.put_file_button.setEnabled(False)
        self.del_file_button.setEnabled(False)
        wwf_box.layout.addWidget(self.get_file_button, alignment=QtCore.Qt.AlignCenter)
        wwf_box.layout.addWidget(self.put_file_button, alignment=QtCore.Qt.AlignCenter)
        wwf_box.layout.addWidget(self.del_file_button, alignment=QtCore.Qt.AlignCenter)
        wid.layout.addWidget(wwf_box, alignment=QtCore.Qt.AlignCenter)
        wid.layout.addWidget(wid.server_tree, alignment=QtCore.Qt.AlignRight)
        return wid

    @qasync.asyncSlot()
    async def ftp_connect(self):
        server_ip = self.server_ip_edit.text()
        server_port = int(self.server_port_edit.text())
        username = self.username_edit.text()
        password = self.password_edit.text()
        self.client_socket = await open_connection_ftp(server_ip, server_port, False, self.pasv_mod_checkbox.isChecked(), username=username, password=password)
        print(self.client_socket)
        if self.client_socket:
            self.connection_indicator.setText("<font color='green'>Connected</font>")
            serv_root_dir_item = QtWidgets.QTreeWidgetItem(['/'])
            serv_root_dir_item.file_path = '/'
            serv_root_dir_item.file_type = 'd'
            serv_root_dir_item.files_added = False
            serv_root_dir_item.setIcon(0, QtGui.QIcon(f'img/folder.png'))
            serv_root_dir_item.addChildren(await self.fill_out_server_item('/'))
            self.wwf_group.server_tree.addTopLevelItem(serv_root_dir_item)
            serv_root_dir_item.files_added = True
            serv_root_dir_item.setExpanded(True)
            serv_root_dir_item.setSelected(True)
        else:
            await self.error_indicator_set_text('Connection failed')

    async def fill_out_server_item(self, path):
        response = await ls(self.client_socket, path)
        dir_list = []
        data_strings = response['data'].splitlines()
        data_stings = data_strings[:-1] if len(data_strings) > 1 else data_strings
        file_list = [list(filter(bool, re.split(r'(\d{1,2}) (\d{2}\:\d{2}|\d{4}) (.*) -> .*|(\d{1,2}) (\d{2}\:\d{2}|\d{4}) (.*)|-> .*| ', item))) for item in data_stings]
        for item in file_list:
            if item[0][0] == 'd':
                dir_list.append({'type': 'd', 'name': item[-1]})
            else:
                dir_list.append({'type': 'f', 'name': item[-1]})

        items = []
        for file in dir_list:
            item = QTreeWidgetItem([file['name']])
            item.file_path = ('' if path == '/' else path) + '/' + file['name']
            item.file_type = file['type']
            item.files_added = False
            icon = 'file_icon' if item.file_type == 'f' else 'folder'
            item.setIcon(0, QtGui.QIcon(f'img/{icon}.png'))
            if item.file_type == 'd':
                item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            items.append(item)
        return self.sort_children(items)
    @qasync.asyncSlot()
    async def get_file(self):
        serv_item = self.wwf_group.server_tree.selectedItems()[0]
        dir_item = self.wwf_group.local_tree.selectedItems()[0]

        response = await get_file(self.client_socket, serv_item.file_path, to_dir=dir_item.file_path)
        if response['state'] == 'successful':
            for idx in range(0, dir_item.childCount()):
                if dir_item.child(idx).text(0) == re.split('[\\/]', serv_item.file_path)[-1]:
                    return None
            new_file_name = re.split('[\\/]', serv_item.file_path)[-1]
            new_file_item = QTreeWidgetItem([new_file_name])
            new_file_item.file_path = ('' if dir_item.file_path == '/' else dir_item.file_path) + '/' + new_file_name
            new_file_item.files_added = True
            new_file_item.file_type = 'f'
            new_file_item.setIcon(0, QtGui.QIcon(f'img/file_icon.png'))
            dir_item.addChild(new_file_item)
        elif response['state'] == 'PermissionError':
            await self.error_indicator_set_text('You have not permissions')

    @qasync.asyncSlot()
    async def put_file(self):
        local_item = self.wwf_group.local_tree.selectedItems()[0]
        dir_item = self.wwf_group.server_tree.selectedItems()[0]
        for idx in range(0, dir_item.childCount()):
            if dir_item.child(idx).text(0) == re.split('[\\/]', local_item.file_path)[-1]:
                messageBox = QtWidgets.QMessageBox()
                messageBox.setText('Do you want to replace the file?')
                messageBox.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                messageBox.open()
                if result == QtWidgets.QMessageBox.No:
                    return None

        get_state = await put_file(self.client_socket, local_item.file_path, \
                                   ('' if dir_item.file_path == '/' else dir_item.file_path) + \
                                   '/' + re.split('[\\/]', local_item.file_path)[-1])
        if get_state['state'] == 'successful':
            for idx in range(0, dir_item.childCount()):
                if dir_item.child(idx).text(0) == re.split('[\\/]', local_item.file_path)[-1]:
                    messageBox = QtWidgets.QMessageBox()
                    messageBox.setText('Do you want to replace the file?')
                    return None
            new_file_name = re.split('[\\/]', local_item.file_path)[-1]
            new_file_item = QTreeWidgetItem([new_file_name])
            new_file_item.file_path = ('' if dir_item.file_path == '/' else dir_item.file_path) + '/' + new_file_name
            new_file_item.file_type = 'f'
            new_file_item.files_added = True
            new_file_item.setIcon(0, QtGui.QIcon(f'img/file_icon.png'))
            dir_item.addChild(new_file_item)
        elif get_state['error'] == 'PermissionError':
            await self.error_indicator_set_text('You have not permissions')

    @qasync.asyncSlot()
    async def del_file(self):
        serv_item = self.wwf_group.server_tree.selectedItems()[0]
        response = await del_file(self.client_socket, serv_item.file_path)
        if response['state'] == 'successful':
            serv_item.parent().removeChild(serv_item)
        else:
            if response['error'] == 'FileDoesNotExist':
                await self.error_indicator_set_text('File does not exist')

    def fill_out_local_item(self, path: str):
        items = []
        for file in os.scandir(path):
            item = QTreeWidgetItem([file.name])
            item.file_path = os.path.abspath(file)
            item.file_type = 'd' if os.path.isdir(file.path) else 'f'
            if item.file_type == 'd':
                item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            item.files_added = False
            icon = 'file_icon' if item.file_type == 'f' else 'folder'
            item.setIcon(0, QtGui.QIcon(f'img/{icon}.png'))
            # item.name = file.name
            items.append(item)
        return self.sort_children(items)

    @qasync.asyncSlot()
    async def get_server_directory_files(self, cl_item):
        items = []
        if cl_item.file_type == 'd':
            if cl_item.files_added:
                return
            for item in await self.fill_out_server_item(cl_item.file_path):
                items.append(item)
        cl_item.files_added = True
        cl_item.addChildren(self.sort_children(items))
    def get_local_directory_files(self, cl_item):
        self.change_button_enable_state()
        if os.path.isdir(cl_item.file_path):
            if cl_item.files_added:
                return
            for item in self.fill_out_local_item(cl_item.file_path):
                cl_item.addChild(item)
        cl_item.files_added = True

    def server_item_click_trigger(self, item, column):
        self.change_button_enable_state()
        if item.file_type == 'd':
            self.get_server_directory_files(item)

    def change_button_enable_state(self):
        try:
            local_selected = self.wwf_group.local_tree.selectedItems()[0]
            server_selected = self.wwf_group.server_tree.selectedItems()[0]
        except IndexError:
            return

        if local_selected.file_type == 'd' and server_selected.file_type == 'f':
            self.get_file_button.setEnabled(True)
            self.put_file_button.setEnabled(False)
            self.del_file_button.setEnabled(True)
        elif local_selected.file_type == 'f' and server_selected.file_type == 'd':
            self.get_file_button.setEnabled(False)
            self.put_file_button.setEnabled(True)
            self.del_file_button.setEnabled(False)
        elif local_selected.file_type == 'f' and server_selected.file_type == 'f':
            self.get_file_button.setEnabled(False)
            self.put_file_button.setEnabled(False)
            self.del_file_button.setEnabled(True)
        else:
            self.get_file_button.setEnabled(False)
            self.put_file_button.setEnabled(False)
            self.del_file_button.setEnabled(False)


    def sort_children(self, items):
        folders = []
        files = []
        for item in items:
            if item.file_type == 'd':
                folders.append(item)
            else:
                files.append(item)
        return folders + files

    async def error_indicator_set_text(self, text):
        self.error_indicator.setText(f"<font color='red'>{text}</font>")
        self.error_indicator.setHidden(False)
        await asyncio.sleep(5)
        self.error_indicator.setHidden(True)


async def main_desktop():
    print(getpass.getuser())
    app = QtWidgets.QApplication([])
    event_loop = qasync.QEventLoop(app)
    widget = AngloFTPWidget()
    widget.resize(800, 600)
    widget.show()

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)

    with event_loop:
        event_loop.run_until_complete(app_close_event.wait())

if __name__ == '__main__':
    asyncio.run(main_desktop())
