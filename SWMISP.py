#! python3
import os
import re
import sys
import time
import binascii
import collections
import configparser

from PyQt5 import QtCore, QtGui, uic
from PyQt5.QtCore import pyqtSlot, Qt
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox, QFileDialog

from serial import Serial
from serial.tools.list_ports import comports


'''
from SWMISP_UI import Ui_SWMISP
class SWMISP(QWidget, Ui_SWMISP):
    def __init__(self, parent=None):
        super(SWMISP, self).__init__(parent)
        
        self.setupUi(self)
'''
class SWMISP(QWidget):
    def __init__(self, parent=None):
        super(SWMISP, self).__init__(parent)
        
        uic.loadUi('SWMISP.ui', self)
        self.setWindowTitle(f'{self.windowTitle()} {"v1.1"}')

        for port, desc, hwid in comports():
            self.cmbPort.addItem(f'{port} ({desc})')

        self.initSetting()

        self.initState()

        self.ser = Serial(baudrate=4800, timeout=1)

        self.tmrSer = QtCore.QTimer()
        self.tmrSer.setInterval(10)
        self.tmrSer.timeout.connect(self.on_tmrSer_timeout)
        self.tmrSer.start()

        self.tmrSer_Cnt = 0
    
    def initSetting(self):
        if not os.path.exists('setting.ini'):
            open('setting.ini', 'w', encoding='utf-8')
        
        self.conf = configparser.ConfigParser()
        self.conf.read('setting.ini', encoding='utf-8')

        if not self.conf.has_section('serial'):
            self.conf.add_section('serial')
            self.conf.set('serial', 'port', '')
            self.conf.set('serial', 'baud', '')

            self.conf.add_section('binary')
            self.conf.set('binary', 'path', '[]')

        index = self.cmbPort.findText(self.conf.get('serial', 'port'))
        self.cmbPort.setCurrentIndex(index if index != -1 else 0)

        index = self.cmbBaud.findText(self.conf.get('serial', 'baud'))
        self.cmbBaud.setCurrentIndex(index if index != -1 else 0)
        
        self.cmbFile.addItems(eval(self.conf.get('binary', 'path')))

    def initState(self):
        self.rcvBuf = ''        # 串口接收缓存

        self.Oper = ''          # 'write'、'check'、'erase'

        self.NowCmd = ''        # 当前正在执行的命令

        self.TryCnt = 0         # 命令发送重试计数器

        self.Timeout = None     # 操作超时时刻

        self.FileTime = None    # 文件修改时间

    @pyqtSlot()
    def on_btnOpen_clicked(self):
        if not self.ser.is_open:
            try:
                self.ser.port = self.cmbPort.currentText().split()[0]
                self.ser.open()
            except Exception as e:
                print(e)
            else:
                self.cmbPort.setEnabled(False)
                self.cmbBaud.setEnabled(False)
                self.btnOpen.setText('关闭串口')

        else:
            self.ser.close()

            self.cmbPort.setEnabled(True)
            self.cmbBaud.setEnabled(True)
            self.btnOpen.setText('打开串口')
    
    def on_tmrSer_timeout(self):
        self.tmrSer_Cnt += 1

        if self.ser.is_open:
            if self.ser.in_waiting > 0:
                self.rcvBuf += self.ser.read(self.ser.in_waiting).decode('latin')

                while True:
                    index = self.rcvBuf.find('\r\n')
                    if index == -1:
                        break

                    else:
                        resp = self.rcvBuf[:index]
                        if self.NowCmd == 'sync' and resp == 'sync':
                            resp = 'OK'

                        elif self.NowCmd == 'version' and re.match(r'M\d{3}V\d{2}A', resp):
                            self.txtStat.append(f'{resp}\n')

                            self.targetInfo(resp[1:4])

                            if self.Oper == 'write':
                                self.uu_encode()

                            resp = 'OK'

                        elif self.NowCmd == 'checksum' and re.match(r'0x[\dABCDEF]{8}', resp):
                            if self.binSum.lower() == resp.lower():
                                self.txtStat.append(f'校验正确！\n\n')
                            else:
                                self.txtStat.append(f'校验错误：读出的校验和（{resp}）!= 文件的校验和（{self.binSum}）！\n\n')

                            self.OperFinish()

                        if resp == 'OK':
                            self.Timeout = time.time() + 2
                            
                            if self.NowCmd == 'sync':
                                self.ser.write(b'version\r\n')
                                self.NowCmd = 'version'

                            elif self.NowCmd == 'version':
                                if self.Oper == 'write':
                                    self.ser.write(b'baudrate %06d\r\n' %int(self.cmbBaud.currentText()))
                                    self.NowCmd = 'baudrate'

                                elif self.Oper == 'erase':
                                    self.ser.write(b'erase 0000 %04d\r\n' %(4096 // self.SECT_SIZE))
                                    self.NowCmd = 'erase'

                                elif self.Oper == 'check':
                                    self.ser.write(b'checksum %07d\r\n' %self.binSize)
                                    self.NowCmd = 'checksum'

                            elif self.NowCmd == 'baudrate':
                                self.ser.baudrate = int(self.cmbBaud.currentText())

                                QtCore.QTimer.singleShot(10, lambda: self.ser.write(b'erase 0000 %04d\r\n' %self.TotalSect))
                                self.NowCmd = 'erase'

                            elif self.NowCmd == 'erase':
                                if self.Oper == 'erase':
                                    self.txtStat.append('擦除完成!\n\n')
                                    self.OperFinish()

                                elif self.Oper == 'write':
                                    self.txtStat.append('擦除完成!\n')
                                    self.ser.write(b'write\r\n')
                                    self.NowCmd = 'write'

                            elif self.NowCmd == 'write':
                                self.ser.write(b'W %s\r\n' %self.uuCode[self.NowPage][self.NowLine])

                                self.barProg.setValue((self.NowPage * self.LinePerPage + self.NowLine) * 100 // (self.TotalPage * self.LinePerPage))

                                self.NowLine += 1
                                if self.NowLine == self.LinePerPage:
                                    self.NowCmd = 'W'

                            elif self.NowCmd == 'W':
                                self.ser.write(b'copy %05d\r\n' %self.NowPage)
                                self.NowCmd = 'copy'

                            elif self.NowCmd == 'copy':
                                self.NowPage += 1
                                self.NowLine = 0

                                if self.NowPage == self.TotalPage:
                                    self.txtStat.append('烧写完成!\n')
                                    self.barProg.setValue(100)

                                    self.ser.write(b'checksum %07d\r\n' %self.binSize)
                                    self.NowCmd = 'checksum'

                                else:
                                    self.ser.write(b'write\r\n')
                                    self.NowCmd = 'write'

                        elif resp in ('E0', 'E1', 'E2', 'E3', 'E4'):
                            if resp == 'E0':
                                self.txtStat.append('命令解析失败\n\n')
                            elif resp == 'E1':
                                self.txtStat.append('FLASH擦除失败\n\n')
                            elif resp == 'E2':
                                self.txtStat.append('FLASH写入失败\n\n')
                            elif resp == 'E3':
                                self.txtStat.append('接收数据校验错误\n\n')
                            elif resp == 'E4':
                                self.txtStat.append('写入跨页或不满页\n\n')

                            self.OperFinish()

                        self.rcvBuf = self.rcvBuf[index+2:]
            
            if self.Timeout and time.time() > self.Timeout:
                if self.NowCmd == 'sync' and self.TryCnt:
                    self.TryCnt -= 1

                    self.syncTarget()

                else:
                    self.txtStat.append('超时，未收到目标板响应\n\n')
                
                    self.OperFinish()

        else:
            if self.tmrSer_Cnt % 100 == 0:
                if self.cmbPort.count() != len(comports()):     # 检测到串口插拔
                    self.cmbPort.clear()
                    for port, desc, hwid in comports():
                        self.cmbPort.addItem(f'{port} ({desc})')

        if self.tmrSer_Cnt % 100 == 0:                          # 检测到文件修改
            path = self.cmbFile.currentText()
            try:
                filetime = os.path.getmtime(path)
            except Exception as e:
                filetime = None

            if (filetime and self.FileTime and filetime != self.FileTime) or (filetime and not self.FileTime):
                self.on_cmbFile_currentIndexChanged(path)

    @pyqtSlot()
    def on_btnWrite_clicked(self):
        self.NowPage = 0
        self.NowLine = 0

        self.OperStart('write')

    @pyqtSlot()
    def on_btnCheck_clicked(self):
        self.OperStart('check')

    @pyqtSlot()
    def on_btnErase_clicked(self):
        self.OperStart('erase', False)  # 擦除操作不需要 bin 文件

    def OperStart(self, oper, check_file=True):
        path = self.cmbFile.currentText()
        if (not check_file) or (os.path.exists(path) and os.path.isfile(path)):
            if self.ser.is_open:
                self.Oper = oper

                self.NowCmd = 'sync'
                self.TryCnt = 2             # 重试 3 次

                self.ser.baudrate = 4800    # 同步在 4800 波特率下进行
                self.syncTarget()

                self.cmbFile.setEnabled(False)
                self.btnFile.setEnabled(False)
                self.btnOpen.setEnabled(False)
                self.btnWrite.setEnabled(False)
                self.btnCheck.setEnabled(False)
                self.btnErase.setEnabled(False)

            else:
                QMessageBox.critical(self, '串口未打开', '串口未打开，请打开串口重试', QMessageBox.Ok)

        else:
            QMessageBox.critical(self, '文件不存在', '文件不存在，请指定正确的文件路径重试', QMessageBox.Ok)

    def OperFinish(self):
        self.Timeout = None
        
        self.cmbFile.setEnabled(True)
        self.btnFile.setEnabled(True)
        self.btnOpen.setEnabled(True)
        self.btnWrite.setEnabled(True)
        self.btnCheck.setEnabled(True)
        self.btnErase.setEnabled(True)

    def syncTarget(self):
        self.ser.dtr = 1    # 接目标芯片 BOOT 引脚
        self.ser.rts = 0    # 接目标芯片 RESET 引脚
        self.Timeout = time.time() + 1
        QtCore.QTimer.singleShot(10, lambda: self.ser.setRTS(1))
        QtCore.QTimer.singleShot(50, lambda: self.ser.write(b'sync\r\n'))

    @pyqtSlot()
    def on_btnFile_clicked(self):
        path, filter = QFileDialog.getOpenFileName(caption='要烧写的文件', filter='二进制文件 (*.bin *.hex)', directory=self.cmbFile.currentText())
        if path:
            self.cmbFile.insertItem(0, path)
            self.cmbFile.setCurrentIndex(0)

    @pyqtSlot(str)
    def on_cmbFile_currentIndexChanged(self, path):
        if os.path.exists(path) and os.path.isfile(path):
            self.FileTime = os.path.getmtime(path)

            if path.endswith('.hex'):
                self.binCode = parseHex(path)
            else:
                self.binCode = open(path, 'rb').read()

            self.binSum = f'0x{sum(bytearray(self.binCode))%0xFFFFFFFF:08X}'

            self.linSum.setText(self.binSum)

            self.binSize = len(self.binCode)

            self.lblSize.setText(f'{self.binSize//1024}K {self.binSize%1024} bytes')

        else:
            self.FileTime = None

            self.linSum.setText('文件不存在')

    def targetInfo(self, name):
        if name in ('320', '341', '181', '190'):
            self.SECT_SIZE = 4096

        elif name in ('260', ):
            self.SECT_SIZE = 2048

        elif name in ('220', '211'):
            self.SECT_SIZE = 1024

        else:
            self.SECT_SIZE = 512

        self.PAGE_SIZE = 256

    def uu_encode(self):
        self.binCode += b'\xFF' * (self.PAGE_SIZE - self.binSize % self.PAGE_SIZE)

        self.TotalSect = (self.binSize + (self.SECT_SIZE - 1)) // self.SECT_SIZE   # 需要擦除的扇区数
        self.TotalPage = len(self.binCode) // self.PAGE_SIZE

        self.LINE_SIZE = 45     # 45 字节数据，经 uucode 编码变成 60 字节后发送

        self.LinePerPage = (self.PAGE_SIZE + (self.LINE_SIZE - 1)) // self.LINE_SIZE

        self.uuCode = []
        for i in range(self.TotalPage):
            page = self.binCode[self.PAGE_SIZE*i : self.PAGE_SIZE*(i+1)]

            self.uuCode.append([])
            for j in range(self.LinePerPage):
                line = page[45*j : 45*(j+1)]
                sumi = sum(bytearray(line))
                self.uuCode[i].append(binascii.b2a_uu(line)[:-1].replace(b' ', b'\x60') + b' %03d' %(sumi&0xFF))

    @pyqtSlot()
    def on_btnClear_clicked(self):
        self.txtStat.clear()

        self.barProg.setValue(0)

    def closeEvent(self, evt):
        self.tmrSer.stop()
        self.ser.close()
        
        self.conf.set('serial', 'port', self.cmbPort.currentText())
        self.conf.set('serial', 'baud', self.cmbBaud.currentText())

        path = [self.cmbFile.currentText()] + [self.cmbFile.itemText(i) for i in range(self.cmbFile.count())]
        self.conf.set('binary', 'path', repr(list(collections.OrderedDict.fromkeys(path))))     # 保留顺序去重

        self.conf.write(open('setting.ini', 'w', encoding='utf-8'))


def parseHex(file):
    ''' 解析 .hex 文件，提取出程序代码，没有值的地方填充0xFF '''
    data = ''
    currentAddr = 0
    extSegAddr  = 0     # 扩展段地址
    for line in open(file, 'rb').readlines():
        line = line.strip()
        if len(line) == 0: continue
        
        len_ = int(line[1:3],16)
        addr = int(line[3:7],16) + extSegAddr
        type = int(line[7:9],16)
        if type == 0x00:
            if currentAddr != addr:
                if currentAddr != 0:
                    data += chr(0xFF) * (addr - currentAddr)
                currentAddr = addr
            for i in range(len_):
                data += chr(int(line[9+2*i:11+2*i], 16))
            currentAddr += len_
        elif type == 0x02:
            extSegAddr = int(line[9:9+4], 16) * 16
        elif type == 0x04:
            extSegAddr = int(line[9:9+4], 16) * 65536
    
    return data


if __name__ == "__main__":
    app = QApplication(sys.argv)
    isp = SWMISP()
    isp.show()
    app.exec()
