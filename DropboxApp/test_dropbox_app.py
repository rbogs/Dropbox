""" ******************************************************************************
Copyright:      Mr Bean's Company 2021
Module:         test_dropbox_app.py
Author:         Roman Bogusz
Description:    Dropbox app test module.
                Test cases implemented using buildin Python unittest IsolatedAsyncioTestCase module.

                Curren code coverage of dropbox_app.py: 83%


Limitations / known issues:
                - ResourceWarning: Enable tracemalloc to get the object allocation traceback
                - RuntimeError: Event loop is closed 
                - asyncio exception handling
ToDo:           
                - test case descriptions
                - implment test cases for 'same content' to ensure files are copied on server side rather than uploaded
                - implement negative test cases - exceptions etc.
                - implement stress test cases:
                    - multiple file changes at once
                    - big files
"""
import os
import random
import unittest
from unittest import IsolatedAsyncioTestCase
import asyncio
import shutil
import filecmp


import dropbox_app

print('\ndropbox_app unit test execution... \n')


file_set_1 = {'\\f1.txt', '\\f2.txt', '\\f3.txt'}
file_set_2 = {'\\f4.jpg', '\\f5.jpg', '\\f6.jpg'}


def generate_file_with_random_content(file_path_name, size):
    
    path, file = os.path.split(file_path_name)
    if not os.path.isdir(path):
        os.makedirs(path)
    with open(file_path_name, 'w') as f:
        for num in range(size):
            f.write(str(random.randrange(9)))
    f.close()


def generate_dir(dir_name, file_list=None):
    this_file_dir, f = os.path.split(os.path.realpath(__file__))

    # Create directory if doesnt exist yet
    if not os.path.isdir(dir_name):
        os.mkdir(dir_name)
    
    # Generate files is specified
    if file_list is not None:
        for f in file_list:
            generate_file_with_random_content(this_file_dir + '\\' + dir_name + f, 100)


def are_dcmp_the_same(dcmp):
    """
    Checks provided dcmp instance to find out whether specified directories the same
    note: same means same files, files content, subdirectories etc.
    """
    are_the_same = True

    # Check whether files which are only in dir1 or dir2 or if same name files but different content
    if dcmp.left_only != [] or \
        dcmp.right_only != [] or \
            dcmp.diff_files != []:
        are_the_same = False
    else:
        
        # Do above step for subdirectories recursively
        for sub_dcmp in dcmp.subdirs.values():
            are_sub_the_same = are_dcmp_the_same(sub_dcmp)
            if not are_sub_the_same:
                are_the_same = False

    return are_the_same


def are_dir_trees_the_same(dir1, dir2):

    dcmp = filecmp.dircmp(dir1, dir2)
    return are_dcmp_the_same(dcmp)


# class TestDropboxApp(unittest.TestCase):
class TestDropboxApp(IsolatedAsyncioTestCase):

    async def test_server_client_synch(self):
        """
        Create nested directories tree for client with random files generated.
        Create empty dir for server.
        Initialise server & client and ensure that server dir content gets synchronised with client dir content.
        Remove file on client side, check server synchronised.
        Add file on client side, check server synchronised.
        Rename file on client side, check server synchronised.
        """
        
        client_dir = 'client_dir'
        server_dir = 'server_dir'
        
        # *****   Client-server synchronisation on init   *****
        # Generate client dir with files added
        generate_dir(client_dir, file_set_1)
        generate_dir(client_dir + '//subd1', file_set_1)
        generate_dir(client_dir + '//subd2', file_set_1)
        generate_dir(client_dir + '//subd2//subd3', file_set_1)
        
        # Generate empty server dir
        generate_dir(server_dir)
        
        # Check client and server directories are different
        same = are_dir_trees_the_same(client_dir, server_dir)
        self.assertFalse(same)
        
        # Enable and init server
        server = dropbox_app.DropboxServerApp(server_dir)
        server.init_app()
        await asyncio.sleep(0.5)

        # Enable and init client
        server_ip, server_port = server.get_server_ip_and_port()
        client = dropbox_app.DropboxClientApp(client_dir)
        client.init_app(server_ip, server_port)
        
        # Allow files to be synchronised
        await asyncio.sleep(1.)
    
        # check dir are the same after sync
        same = are_dir_trees_the_same(client_dir, server_dir)
        self.assertTrue(same)

        # *****   Client file deletion synch   *****
        # delete file on client side
        file_to_remove = list(file_set_1)[0]
        os.remove(client_dir + file_to_remove)
        
        # Allow sync
        await asyncio.sleep(1.)

        # Check client and server directories are same
        same = are_dir_trees_the_same(client_dir, server_dir)
        self.assertTrue(same)

        # *****   Client files assition synch   *****
        # Add subdirectory with files on client side
        generate_dir(client_dir + '//subdx', file_set_2)

        # Allow sync
        await asyncio.sleep(1.)

        # Check client and server directories are different
        same = are_dir_trees_the_same(client_dir, server_dir)
        self.assertTrue(same)

        # *****   Client file rename synch   *****
        # Rename file on client side
        file_to_rename = list(file_set_1)[1]
        os.rename(client_dir + file_to_rename, client_dir + '\\new_file_name.txt')

        # Allow sync
        await asyncio.sleep(1.)

        # Check client and server directories are different
        same = are_dir_trees_the_same(client_dir, server_dir)
        self.assertTrue(same)

        # Close server and client
        client.stop_app()
        server.stop_app()
        await asyncio.sleep(1.)

        # Delete created directories
        shutil.rmtree(client_dir) 
        shutil.rmtree(server_dir)
        
    async def test_common_local_dir_content(self):
        
        # Generate dir and files
        generate_dir('common_dir', file_set_1)
        
        # Create DropboxAppCommon instance for generate directory
        comm = dropbox_app.DropboxAppCommon('common_dir')
        
        # obtain dir content and ensure it matches previously generated file set
        loc_content = comm.obtain_local_dir_current_content()
        self.assertEqual(file_set_1, set(loc_content))
        
        # Delete previously created dir
        shutil.rmtree('common_dir') 
        
    async def test_server_with_none_input_dir(self):
        """
        Instantiate server classs with None directory provided.
        Check app doesn't crash and server content is empty
        """
        
        # Provide None directory, check content is empty and no Exception
        server = dropbox_app.DropboxServerApp(None)
        self.assertEqual(server._latest_local_dir_content, {})
      
    async def test_server_check_dir_content_match(self):
        """
        Instantiate server classs with provided valid directory.
        Check obtained server content matches with the provided directory.
        """
        
        # Generate dir and files
        generate_dir('dir1', file_set_1)

        # Create server of the same dir and ensure content of server is right
        server = dropbox_app.DropboxServerApp('dir1')
        serv_content = set(server._latest_local_dir_content.keys())
        self.assertEqual(serv_content, set(file_set_1))

        # Delete previously created dir
        shutil.rmtree('dir1') 

    async def test_server_init_app_with_invalid_ip(self):
        """
        Init server app with invalid IP.
        Check
        """
        
        # Provide None directory, check content is empty
        server = dropbox_app.DropboxServerApp('dir1')

        # Init server with invalid IP provided
        server.init_app('invalid ip')        
        
        # Allow time to start
        await asyncio.sleep(0.1)
        
        # Init server with invalid IP provided
        self.assertIs(server.server, None)
        
        await asyncio.sleep(0.005)

        server.stop_app()
        
        # Delete previously created dir
        shutil.rmtree('dir1') 

    async def test_server_init_app_with_host_ip(self):
        """
        Init server app with invalid IP.
        Check
        """ 
        # Provide None directory, check content is empty
        server = dropbox_app.DropboxServerApp('dir1')

        # Init server with local host (default) IP
        server.init_app()
        
        # Allow time to start
        await asyncio.sleep(0.1)
        
        # Assert that server is not created
        # print('server.server:',server.server, type(server.server))
        self.assertIsInstance(server.server, asyncio.base_events.Server)
        await asyncio.sleep(0.005)
        
        server.stop_app()
        
        # Delete previously created dir
        shutil.rmtree('dir1') 
        
    async def test_server_init_app_called_twice(self):
        """
        Init server app with invalid IP.
        Check
        """ 
        # Provide None directory, check content is empty
        server = dropbox_app.DropboxServerApp('dir1')

        # Init server with local host (default) IP
        server.init_app()
        
        # Allow time to start
        await asyncio.sleep(0.1)
        
        # Assert that server is not created
        # print('server.server:',server.server, type(server.server))
        self.assertIsInstance(server.server, asyncio.base_events.Server)
        await asyncio.sleep(0.005)

        # Init server with local host (default) IP
        server.init_app()
        await asyncio.sleep(0.1)
        
        server.stop_app()
        
        # Delete previously created dir
        shutil.rmtree('dir1') 
        
    async def test_server_get_server_ip_and_port(self):
        
        ip = '127.0.0.1'
        port = 65431
        
        # Init server with local host (default) IP
        server = dropbox_app.DropboxServerApp('dir1')
        server.init_app(ip, port)
        
        # Allow time to start
        await asyncio.sleep(0.1)
    
        # Check whether returned ip and port match the requested ones
        ret_ip, ret_port = server.get_server_ip_and_port()
        self.assertEqual(ip, ret_ip)
        self.assertEqual(port, ret_port)
        
        server.stop_app()

        # Delete previously created dir
        shutil.rmtree('dir1') 

    async def test_instant_client_with_none_dir(self):
        """
        Instantiate client classs with None directory provided.
        Check app doesn't crash and client content is empty
        """
        
        # Provide None directory, check content is empty and no Exception
        client = dropbox_app.DropboxClientApp(None)
        self.assertEqual(client._latest_local_dir_content, {})
        
    async def test_client_init_app_with_invalid_ip(self):
        
        # Create client
        client = dropbox_app.DropboxClientApp('dir2')
        
        # Init client with None IP / Port
        client.init_app(None, None)
        await asyncio.sleep(0.1)
        
        # Init client with invalid IP / Port
        client.init_app('invalid ip', 'invalid port')
        await asyncio.sleep(0.1)

        # Delete previously created dir
        shutil.rmtree('dir2') 


if __name__ == '__main__':
    unittest.main()
