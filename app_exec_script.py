""" ******************************************************************************
Copyright:      Mr Bean's Company 2021
Module:         app_exec_script.py
Author:         Roman Bogusz
Description:    This script can be used to manually test Dropbox application.
"""

import sys
import asyncio
import DropboxApp

# Default IP & Port
server_ip = "127.0.0.1"
server_port = 65431


async def main():

    # Start server
    server_app.init_app()
    
    # Obtain server IP and port 
    server_ip, server_port = server_app.get_server_ip_and_port()
    
    # Start client
    client_app.init_app(server_ip, server_port)
    
    while 1:
        await asyncio.sleep(0.5)


if __name__ == "__main__":

    # asyncio Win issue workaround as per: https://githubmemory.com/repo/Dinnerbone/mcstatus/issues/133
    if sys.version_info[0] == 3 and sys.version_info[1] >= 8 and sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Create Dropbox APP
    server_app = DropboxApp.DropboxServerApp(r"D:\temp")         # @ToDo: specify server directory
    client_app = DropboxApp.DropboxClientApp(r"D:\2004-08-282")  # @ToDo: specify client directory

    # Obtain asyncio event loop and set exception handler
    event_loop = asyncio.get_event_loop()
    event_loop.set_exception_handler(server_app.exception_handler)
    
    # Start loop and execute until terminated by user in command line
    try:
        event_loop.run_until_complete(main())
    except KeyboardInterrupt:
        server_app.stop_app()
        client_app.stop_app()
        print('Script interrupted by the user.')
