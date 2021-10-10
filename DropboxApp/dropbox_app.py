""" ******************************************************************************
Copyright:      Mr Bean's Company 2021
Module:         dropbox_app.py
Author:         Roman Bogusz
Description:    This dropbox application is intended to keep track of local client directory and 
                maintain copy of that directory on allocated server.
                Features: 
                    - optimise uploads to avoid uploading to server files which already exist there
                      (including files with the same content but different names or location). 
                    - uses calculated CRC of each file to determine whether files are the same / different.
                        A change is required to use file size & date instead of crc to determine whether local client
                        dir is modified.
                    - supports subdirectories
                    - file names are considered as case sensitive (Linux compatibility)
                    - app execution info & errors logged into dropbox.log using logging module


Limitations / known issues:
                - monitoring of changes in local dir is based on crc calculation which unefficient for big files. 
                    e.g. file modification date and size shall be used instead.
                - empty directories not synchronised properly
                - create config file for things like default server port etc.
                - no confirmation (feetback) from server to confirm requested action executed OK
                - files partial content not checked (ref. 'Bonus 2')
                - asyncio exceptions handling - how to?!
                - single server to single client session tested only
                - app tested on local host only
                - app tested on Win10 only
                - max message size: 4096 bytes

ToDo:
                - make methods & members local
"""

import asyncio
import socket
import os
import time
import abc
import copy
import zlib
import logging
import json
import shutil


# ToDo: make following values configurable (e.g. import from config file)
default_server_port = 65431
logging.basicConfig(format='%(asctime)s:%(msecs)-5d::%(levelname)-5s: %(name)-23s  %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG,
                    handlers=[logging.FileHandler('dropbox.log', 'w', 'utf-8')])


class DropboxCommsProtocol:
    """
    Client <-> Server communication protocol (commands).
    """
    read_dir_content = '::CMND:READ_DIR_CONTENT::'
    upload_file = '::CMND:UPLOAD_FILE::'
    delete_file = '::CMND:DELETE_FILE::'
    copy_and_rename_file = '::CMND:COPY_AND_RENAME_FILE::'
    move_and_rename_file = '::CMND:MOVE_AND_RENAME_FILE::'
    end_of_msg = '::>>END<<::'


CMND = DropboxCommsProtocol


class DropboxAppCommon:
    __metaclass__ = abc.ABCMeta
    
    def __init__(self, dir_to_monitor):
        self._latest_local_dir_content = []
        self.reader = None
        self.writer = None

        # Init logger
        self.log = logging.getLogger(__name__)
        
        # If specified dir does not exist then attempt to create it
        self.dir_to_monitor = dir_to_monitor
        if self.dir_to_monitor is None:
            self.log.exception('CMN: None directory provided')
        else:
            if not os.path.isdir(self.dir_to_monitor):
                try:
                    os.mkdir(self.dir_to_monitor)
                except Exception as e:
                    self.log.exception('CMN: exception creating "{}" directory: {}'.format(self.dir_to_monitor, e))
                    self.dir_to_monitor = None

        # Obtain initial content of specified directory
        self._latest_local_dir_content = self.obtain_local_dir_current_content()

    def obtain_local_dir_current_content(self):
        """
        Obtain content of local directory. 
        Content is stored in dictionary where keys are file names (relative path + name) and keys are calculated CRCs.
        Returns obtained content dictionary.
        """
        dir_current_content = {}
        if self.dir_to_monitor is not None:
            for subdir, dirs, files in os.walk(self.dir_to_monitor):
                for file in files:
                    
                    file_found = os.path.join(subdir, file)

                    # Turn into relative to monitored directory
                    
                    file_found_relative = file_found.split(self.dir_to_monitor)[-1]
                    
                    # Add to the list of monitored dir content
                    file_crc = self.calc_file_crc32(file_found)
                    if file_crc is not None:
                        dir_current_content[file_found_relative] = file_crc

        self.log.debug('CMN: obtaining local directory content')
        return dir_current_content

    def exception_handler(self, loop, context):
        """
        Asyncio exception handler?!
        """
        msg = context.get('exception', context['message'])
        logging.error(f'Caught exception: {msg}')
        logging.info('Shutting down...')
        self.stop_app()
    
    def calc_file_crc32(self, path_file):
        """
        Calculate CRC32 of specified file using zlib.crc32 method.
        Return calculated crc.
        """
        crc32 = None
        try:
            f = open(path_file, 'rb')
        except OSError as e:
            self.log.exception('CMN: exception opening {} file: {}'.format(path_file, e))
        else:
            # Get file content
            try:
                content = f.readlines()
            except OSError as e:
                self.log.exception('CMN: error reading {} file: {}'.format(path_file, e))
            else:
                f.close()
            
                # Calculate CRC32
                crc32 = 0
                for line in content:
                    crc32 = zlib.crc32(line, crc32)
                
        return crc32
        
    @abc.abstractmethod
    def init_app(self, ip, port):
        return

    @abc.abstractmethod
    def stop_app(self):
        return


class DropboxServerApp(DropboxAppCommon):
    
    def __init__(self, dir_to_monitor):
        super().__init__(dir_to_monitor)
        self.server = None
        self.server_ip = None
        self.server_port = None
        self.is_running = False

    def init_app(self, server_ip=None, server_port=None):
        """
        Initialise server application - start server listen task.
        If IP and Port are not specified then use localhost and default Port.
        """
        # Use provided IP. If not provided then determine host IP and use it
        self.server_ip = server_ip
        if self.server_ip is None:
            self.server_ip = socket.gethostbyname(socket.gethostname())
    
        # If port number not provided then use default one
        self.server_port = server_port
        if self.server_port is None:
            self.server_port = default_server_port
    
        # If server already running then stop and start again
        if self.is_running:
            self.stop_app()
            time.sleep(0.1)
            
        # Create server task
        asyncio.create_task(self.server_task())
    
    async def server_task(self):
        """
        Server periodic (infinitive) task - server listenes for connections from client on specified IP and port. 
        """
        self.log.info('SR: Server task creation...')
        
        # Start server
        try:
            self.server = await asyncio.start_server(self.client_connect_callback, self.server_ip, self.server_port)
        except Exception as e:
            self.log.exception('SR: Sexception starting server - {}'.format(e))
            await asyncio.sleep(0.005)
        else: 
            addr = self.server.sockets[0].getsockname()
            self.log.info(f'SR: Serving on IP={addr}')
            
            self.is_running = True
            async with self.server:
                await self.server.serve_forever()
                await asyncio.sleep(0.005)
    
    async def client_connect_callback(self, reader, writer):
        """
        A callback method which is executed each time a client is connected to the server.
        This method reads message from client and calls command dispatcher to determine type of request.
        Note: currently max rx message size is 4096 bytes.
        """
        self.reader = reader
        self.writer = writer

        # Read message from client:
        data = await self.reader.read(4096)  # Max request size (?!)
        try:
            message = data.decode()
        except Exception as e:
            self.log.exception('SR: Exception decoding cilent message: {}'.format(e))
        else:

            # Parse command received from client
            await self.command_dispatcher(message)
            
        await asyncio.sleep(0.1)
        
    async def command_dispatcher(self, rx_message):
        """
        This methods analyses message received from client to determine type of action
        to be executed by the server.
        
        """
        self.log.info('SR: command received from client {}'.format(rx_message))
        # Command: READ Server directory content
        if CMND.read_dir_content in rx_message:

            # Obtain local dir content
            server_dir_content = self.obtain_local_dir_current_content()

            # Dump directory content dictionary into json
            server_dir_content_str = json.dumps(server_dir_content)
            
            # Send content with end of command separator added at the end
            await self.send_message(server_dir_content_str)

        # Command: COPY AND RENAME file in server directory
        if CMND.copy_and_rename_file in rx_message:
            
            # Parse Rx message to obtain source and destination file path+name
            msg_list = rx_message.split('::')
            current_file_path_name = self.dir_to_monitor + msg_list[-2]
            new_file_path_name = self.dir_to_monitor + msg_list[-1]
            
            # Copy and rename existing server file to a requested location
            try:
                shutil.copy(current_file_path_name, new_file_path_name)
            except IOError as e:
                self.log.exception('SR: Error copying file {} to {}: {}}'.format(current_file_path_name, new_file_path_name, e))

        # Command: MOVE AND RENAME file in server directory
        if CMND.move_and_rename_file in rx_message:
            
            # Parse Rx message to obtain source and destination file path+name
            msg_list = rx_message.split('::')
            current_file_path_name = self.dir_to_monitor + msg_list[-2]
            new_file_path_name = self.dir_to_monitor + msg_list[-1]
            
            # Move and rename existing server file to a requested location
            try:
                shutil.move(current_file_path_name, new_file_path_name)
            except IOError as e:
                self.log.exception('SR: Error moving file {} to {}: {}'.format(current_file_path_name, new_file_path_name, e))
                
        # Command: DELETE a file in server directory
        if CMND.delete_file in rx_message:
            
            # Parse Rx rx_message to obtain file to delete
            file_to_delete = self.dir_to_monitor + rx_message.split('::')[-1]
            
            # Delete requested file from server
            try:
                os.remove(file_to_delete)
            except IOError as e:
                self.log.exception('SR: Error deleting file {}: {}'.format(file_to_delete, e))
            
        # Command: UPLOAD a file in server directory
        if CMND.upload_file in rx_message:
            file_to_upload = self.dir_to_monitor + rx_message.split('::')[2]
            
            # If file to be in subdirectory then create the subdirectory
            path, file = os.path.split(file_to_upload)
            if not os.path.isdir(path):
                os.makedirs(path)
            
            # Create file as per requested name:
            with open(file_to_upload, 'wb') as f:
                
                while True:
                    # Read stream until no data
                    data = await self.reader.read(4096)
                    try:
                        f.write(data)
                        if data == b'':
                            break
                    except IOError as e:
                        self.log.exception('SR: exception writing {} file: {}'.format(file_to_upload, e))
                        break
                        
        await asyncio.sleep(0.05)
   
    async def send_message(self, message_to_send):
        """
        Send specified message to the client using asyncio write() method.
        End of message delimiter is attached to each message to allow client to determine end of message.
        """
        # Send content encoded and with end of command separator added at the end
        message = message_to_send.encode() + CMND.end_of_msg.encode()
        self.log.info('SR: Tx message: {}'.format(message))
        self.writer.write(message)
        
        await asyncio.sleep(0.005)
    
    def stop_app(self):
        """
        Stop server - stop server task.
        """
        
        self.log.info('SR: closing server...')
        
        if self.server is not None:
            self.server.close()
            
        self.is_running = False

    def get_server_ip_and_port(self):
        return self.server_ip, self.server_port

    
class DropboxClientApp(DropboxAppCommon):
    
    def __init__(self, dir_to_monitor):
        super().__init__(dir_to_monitor)
        self._is_client_task_on = False
        self.rem_server_ip = None
        self.rem_server_port = None
        self.loc_dir_content_previous = None
        
    def init_app(self, rem_server_ip, rem_server_port):
        """
        Initialise client application - start client task.
        """
        
        self.log.info('CL: Client initialisation.')
        
        # Assign provided server IP and Port
        if rem_server_ip is None or rem_server_port is None:
            self.log.error('CL: None IP / Port provided to init_app.')
        else:
            self.rem_server_ip = rem_server_ip
            self.rem_server_port = rem_server_port
            
            # If client dir. content doesn't match server content then synchronise
            asyncio.create_task(self.synchronise_server())

            # Start client task to monitor changes in local directory
            self._is_client_task_on = True
            asyncio.create_task(self.client_task())

    async def synchronise_server(self, local_content=None):
        """
        This method is used to synchronise client and server content by issuing action request commands to the server.
        This method checks for the type of difference between client and server and based on that determines which
        command to issue to the server:
            - Upload file
            - Copy and rename file (copy on server side, to avoid uploading content which already exists on server)
            - Move and rename file (move on server side, to avoid uploading content which already exists on server)
        
        Algorithm is optimised to avoid uploading files to the server which already exist.
        
        Files comparison is done using calculated CRC of each file.
        
        Once client changes are synchronised to server a 'server cleanup' procedure is then called to remove files
        which exist on the server but do not exist on the client.
        
        """
        is_synch_successful = True
        
        self.log.info('CL: Server synchronisation procedure.')
        
        # Obtain server dir content
        read_attempts = 3
        server_content = None
        while read_attempts > 0:
            server_content = await self.read_server_dir_content()
            if server_content is None:
                read_attempts -= 1
            else:
                break

        if server_content is None:
            is_synch_successful = False
        else:
            # Obtain local dir content
            if local_content is None:    
                local_content = self.obtain_local_dir_current_content()

            # Check if different
            for local_file in local_content:
                
                # Check whether same file path+name exists in server content
                if local_file in server_content:

                    # Same file path+name found in server content; check if CRCs are the same
                    if server_content[local_file] == local_content[local_file]:
                        
                        # Files and CRCs the same, go to next file
                        continue
                       
                # Check if file of the same crc (but different path+name) already exists on server
                # note: this step is to avoid uploading file (entity) which is already on server
                crc_to_find = local_content[local_file]
                is_file_found, same_crc_file = self.search_same_crc_file_in_content(server_content, crc_to_find)
                if not is_file_found:
                    
                    # No file of the same crc so upload it
                    is_action_successful = await self.upload_file_to_server(local_file)
                    if not is_action_successful:
                        is_synch_successful = False

                else:
                    # Check whether found server file has got corresponding file in client content
                    # If not: rmove the file and rename; If yes: copy the file and rename
                    is_corresponding_file_found = False
                    if same_crc_file in local_content:
                        
                        # check if crcs match
                        if server_content[same_crc_file] == local_content[same_crc_file]:
                            is_corresponding_file_found = True
                            
                    if is_corresponding_file_found:
                        
                        # Corresponding file found so copy the file and rename
                        is_action_successful = await self.copy_and_rename_file_on_server(same_crc_file, local_file)
                        if not is_action_successful:
                            is_synch_successful = False
                    else:
                        # Corresponding file not found so move the file and rename
                        is_action_successful = await self.move_and_rename_file_on_server(same_crc_file, local_file)
                        if not is_action_successful:
                            is_synch_successful = False
                            
                await asyncio.sleep(0.05)

        if not is_synch_successful:
            self.log.error('CL: synchronisation error!')
        else:
            
            # Cleanup server (remove fiiles which do not exist in local dir)
            await self.cleanup_server()

        return is_synch_successful

    async def cleanup_server(self):
        """
        Method removes files from the server which do not exist in client's directory.
        """

        self.log.info('CL: server cleanup procedure.')
        is_cleanup_successful = True

        # Obtain server dir content
        read_attempts = 3
        server_content = None
        while read_attempts > 0:
            server_content = await self.read_server_dir_content()
            if server_content is None:
                read_attempts -= 1
            else:
                break

        if server_content is None:
            is_cleanup_successful = False
        else:
            # Obtain local dir content
            local_content = self.obtain_local_dir_current_content()

            # Check if different
            for server_file in server_content:
                if server_file not in local_content:
                    await self.delete_file_from_server(server_file)

            for local_file in local_content:
                
                # Check whether same file path+name exists in server content
                if local_file in server_content:

                    # Same file path+name found in server content; check if CRCs are the same
                    if server_content[local_file] == local_content[local_file]:
                        
                        # Files and CRCs the same, go to next file
                        continue

        await asyncio.sleep(0.05)
        
        # ToDo: this procedure does not remove empty directories which do not exist in client
        
        if not is_cleanup_successful:
            self.log.error('CL: server cleanup error!')
 
        return is_cleanup_successful

    @staticmethod
    def search_same_crc_file_in_content(dir_content, crc_to_search):
        """
        A method which searches through provided content dictionary for requested CRC.
        Returns True and file name when CRC found.
        Returns False and None when CRC not found.
        """
        is_same_crc_file_found = False
        file_found = None
        
        # Search for same CRC in server content (to avoid upload if already on server)
        for file in dir_content:
            
            # Check if CRCs are the same
            if crc_to_search == dir_content[file]:
                
                # Same CRC file found on server. 
                is_same_crc_file_found = True
                file_found = file
                break
        
        return is_same_crc_file_found, file_found
                        
    async def read_server_dir_content(self):
        """
        Issue requst to the server to obtain server's current file content.
        """
        
        # Issue read server content command
        request_message = CMND.read_dir_content
        response_json = await self.send_message(request_message, response_expected=True)

        try:    
            server_content = json.loads(response_json)
        except ValueError as e:
            server_content = None
            self.log.exception('CL: exception loading json content: {}'.format(e))

        return server_content

    async def delete_file_from_server(self, file_name):
        """
        Issue requst to delete specified file from the server.
        """
        
        request_message = CMND.delete_file + '{}'.format(file_name)
        await self.send_message(request_message)

    async def upload_file_to_server(self, file_to_upload):
        """
        Issue requst to upload specified file to server.
        """
        
        cmnd_message = CMND.upload_file + '{}::'.format(file_to_upload)
        is_upload_successful = await self.send_file(cmnd_message, file_to_upload)

        return is_upload_successful

    async def copy_and_rename_file_on_server(self, current_file_name, new_file_name):
        """
        Issue requst to the server to copy and rename existing file.
        """
        
        # Copy and rename command: cmnd num + src + dst
        cmnd_message = CMND.copy_and_rename_file + current_file_name + '::' + new_file_name
        await self.send_message(cmnd_message)

        # @ToDo: add a confirmation response from server for action OK / NOK
        
        return True

    async def move_and_rename_file_on_server(self, current_file_name, new_file_name):
        """
        Issue requst to server to move and rename existing file.
        """
        # Copy and rename command: cmnd num + src + dst
        cmnd_message = CMND.move_and_rename_file + current_file_name + '::' + new_file_name
        await self.send_message(cmnd_message)

        # @ToDo: add a confirmation response from server for action OK / NOK
        
        return True

    async def client_task(self):
        """
        Client periodic task (0.5sec period).
        It monitors local client directory content for any changes and once changes detected, 
        they are synchronised to the server using server action request commands.
        """

        while self._is_client_task_on:
            
            print('CL: client task...')
            self.log.debug('CL: client task...')
            
            # Obtain current local dir content
            loc_dir_content_latest = self.obtain_local_dir_current_content()
            
            # Check if previous content already assigned
            if self.loc_dir_content_previous is None:
                self.loc_dir_content_previous = loc_dir_content_latest
                
            # Monitor whether local directory is changed (current vs preevious content)
            content_changed = False
            for file in loc_dir_content_latest:
                if file not in self.loc_dir_content_previous:
                    
                    # File added
                    self.log.info('CL: new file(s) added to the local directory')
                    content_changed = True
                    break
                else:
                    
                    # File exists; check crc is unchanged
                    if loc_dir_content_latest[file] != self.loc_dir_content_previous[file]:
                        
                        # File modified
                        content_changed = True
                        self.log.info('CL: file(s) modified in the local directory')
                        break

            # Compare size (number of files) of current vs previous
            if len(loc_dir_content_latest) != len(self.loc_dir_content_previous):
                
                # File(s) removed
                self.log.info('CL: file(s) removed from the local directory')
                content_changed = True

            # if loc_dir_content_latest[:] != self.loc_dir_content_previous[:]:
            if content_changed:
                
                # Call client-server synchronisation procedure
                # Note: pass current content to func to avoid mismatch (e.g. if many files are being currently copied into dir).
                synch_ok = await self.synchronise_server(loc_dir_content_latest)
                if synch_ok:
                    self.loc_dir_content_previous = copy.deepcopy(loc_dir_content_latest) 

            await asyncio.sleep(0.5)

    async def send_message(self, message, response_expected=False):
        """
        Open connection with the server and send specified message using asyncio write() method.
        Optional response from server is read until end of command delimiter is detected.
        Function returns response from server or None if response not expected.
        """
        
        response = None
        
        # Open connection
        if self.rem_server_ip is not None and self.rem_server_port is not None:
            reader, writer = await asyncio.open_connection(self.rem_server_ip, self.rem_server_port)
        
            # Write message
            writer.write(message.encode())
            
            if response_expected:
                # Read data from server until end of message delimiter detected.
                data = await reader.readuntil(CMND.end_of_msg.encode())
                
                # Strip end of message delimiter from received data:
                response = data.decode().replace(CMND.end_of_msg, '')
                
            writer.close()

        return response

    async def send_file(self, message, file_to_send):
        """
        Open connection with a server and upload specified file to the server using asyncio sendfile() method.
        File upload is preceeded by specified message.
        """
        is_file_sent_successful = False
        
        # Attempt to open file to send
        f = open(self.dir_to_monitor + file_to_send, 'rb')

        # Send file
        reader, writer = await asyncio.open_connection(self.rem_server_ip, self.rem_server_port)
        
        # Send message first (header)
        self.log.info('CL: Upload file "{}" header: {}'.format(file_to_send, message))
        writer.write(message.encode())
        
        # Send file
        loop = asyncio.get_event_loop()
        await loop.sendfile(writer.transport, f)
        
        # @ToDo: add a feedback from server to ensure whether file uploaded successfully
        
        # Close file
        f.close()
        
        # Close socket
        writer.close()
        
        is_file_sent_successful = True
            
        return is_file_sent_successful
        
    def stop_app(self):
        """
        Stop client application task.
        """
        self.log.info('CL: stopping client task...')
        self._is_client_task_on = False 
