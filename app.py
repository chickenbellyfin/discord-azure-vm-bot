import logging
import re
import yaml

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
import discord

logging.basicConfig(
  level=logging.INFO,
  format='%(asctime)s :: %(levelname)s :: %(name)s :: %(message)s',
  handlers=[
    logging.FileHandler("app.log"),
    logging.StreamHandler()
  ]
)
logging.getLogger('azure').setLevel(logging.ERROR)
logging.getLogger('discord').setLevel(logging.ERROR)
logging.getLogger('asyncio').setLevel(logging.ERROR)

with open('config.yaml') as config_file:
  config = yaml.safe_load(config_file)

discord_bot_token = config['discord_bot_token']

discord_bot_channel_id = int(config['channel_id'])

az_tenant_id = config['az_tenant_id']
az_client_id = config['az_client_id']
az_client_secret = config['az_client_secret']

az_subscription_id = config['az_subscription_id']

az_credential = ClientSecretCredential(az_tenant_id, az_client_id, az_client_secret)
az_compute_client = ComputeManagementClient(az_credential, az_subscription_id)

discord_client = discord.Client()

az_resource_group = config['az_resource_group']
az_vm = config['az_vm']
vm_name = config['vm_name']

# Map azure power states to simplified power state
power_state_map = {
  'stopped': {'deallocated', 'deallocating', 'stopped', 'unknown', 'stopping'},
  'running': {'running'},
  'starting': {'starting'}
}

def vm_power_state():
  instance_view = az_compute_client.virtual_machines.instance_view(az_resource_group, az_vm)
  for status in instance_view.statuses:
    if status.code.startswith('PowerState/'):
      logging.info(f'Power state: {status.code}')
      az_state = status.code[len('PowerState/'):]
      for key in power_state_map.keys():
        if az_state in power_state_map[key]:
          return key
      logging.error(f'{az_state} not in power_state_map')
      return 'unknown'
  logging.error("No power state in statuses")
  return 'unknown'

async def send_help_text(message):
  await message.channel.send(f"""
    Usage: @{discord_client.user.display_name} <command>
    **status**: Current server running status
    **start**: Start the {vm_name} server
    **restart**: Restart the {vm_name} server
    **help**: this
    """
  )

async def command_status(message):
  status = vm_power_state()
  await message.channel.send(f'{vm_name} Status: {status}')

async def command_start(message):
  status = vm_power_state()
  if status == 'running':
    await message.channel.send(f"{vm_name} is already running")
  elif status == 'starting':
    await message.channel.send(f"{vm_name} is already starting")
  else:    
    await message.channel.send(f"Starting {vm_name}...")
    result = az_compute_client.virtual_machines.begin_start(az_resource_group, az_vm).wait()
    await command_status(message)

async def command_restart(message):
    status = vm_power_state()
    if status == 'running' or status == 'starting':
      await message.channel.send(f"Restarting {vm_name}...")
      result = az_compute_client.virtual_machines.begin_restart(az_resource_group, az_vm).result()
      await command_status(message)
    else:
      await message.channel.send(f"{vm_name} is not currently running.")

@discord_client.event
async def on_ready():
  logging.info(f'Connected to discord as {discord_client.user}')

@discord_client.event
async def on_message(message):
  bot_mentioned = False
  for member in message.mentions:
    if member.id == discord_client.user.id:
      bot_mentioned = True
  
  if bot_mentioned and message.channel.id == discord_bot_channel_id:
    logging.info(f"Bot mentioned: '{message.content}'")
    tokens = re.split('\s+', message.content)
    if len(tokens) == 2:
      command = tokens[1]
      if command == 'help':
        await send_help_text(message)
      elif command == 'status':
        await command_status(message)
      elif command == 'start':
        await command_start(message)
      elif command == 'restart':
        await command_restart(message)
    else:
      await send_help_text(message)

discord_client.run(discord_bot_token)