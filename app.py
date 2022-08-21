import logging
import yaml
import shlex

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
import discord

EYES='👀'
CHECK='✅'
GREEN_CIRCLE='🟢'
RED_CIRCLE='🔴'
YELLOW_CIRCLE='🟡'


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

intents = discord.Intents.default()
discord_client = discord.Client(intents=intents)


vms = {}
for vm_config in config['vms']:
  key = list(vm_config.keys())[0]
  vms[key] = vm_config[key]
configured_vms_str = ', '.join(vms.keys())

# Map azure power states to simplified power state
power_state_map = {
  'stopped': {'deallocated', 'deallocating', 'stopped', 'unknown', 'stopping'},
  'running': {'running'},
  'starting': {'starting'}
}

power_state_to_emoji = {
  'stopped': RED_CIRCLE,
  'running': GREEN_CIRCLE,
  'starting': YELLOW_CIRCLE
}

def vm_power_state(vm):
  instance_view = az_compute_client.virtual_machines.instance_view(vm['az_resource_group'], vm['az_vm'])
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

def get_member():
  return discord_client.get_channel(discord_bot_channel_id).guild.get_member(discord_client.user.id)

async def send_help_text(message, args):
  await message.channel.send(f"""
    Usage: @{discord_client.user.display_name} <command>
    **status**: Check status of all servers
    **start** <server>: Start a server
    **stop** <server>: Stop a server
    **restart** <server>: Restart a server
    **help**: this

    Available Servers: {configured_vms_str}
    """
  )

async def command_status(message, args):
  status_message=""
  for vm_key, vm in vms.items():
    status = vm_power_state(vm)
    emoji = power_state_to_emoji[status]
    status_message += f"{emoji} {vm['name']} ({vm_key})\n"

  await message.channel.send(f'```{status_message}```')

async def command_start(message: discord.Message, args):
  if len(args) < 1 or args[0] not in vms.keys():
    await message.reply(f'Must specify one of: {configured_vms_str}')
    return

  vm = vms[args[0]]
  status = vm_power_state(vm)
  if status == 'running':
    await message.reply(f"{vm['name']} is already running")
  elif status == 'starting':
    await message.reply(f"{vm['name']} is already starting")
  else:    
    await message.add_reaction(EYES)
    result = az_compute_client.virtual_machines.begin_start(vm['az_resource_group'], vm['az_vm']).wait()
    await message.remove_reaction(EYES, get_member())
    await message.add_reaction(CHECK)


async def command_restart(message, args):
    if len(args) < 1 or args[0] not in vms.keys():
      await message.reply(f'Must specify one of: {configured_vms_str}')
      return

    vm = vms[args[0]]
    status = vm_power_state(vm)
    if status == 'running' or status == 'starting':
      await message.add_reaction(EYES)
      result = az_compute_client.virtual_machines.begin_restart(vm['az_resource_group'], vm['az_vm']).result()
      await message.remove_reaction(EYES, get_member())
      await message.add_reaction(CHECK)
    else:
      await message.channel.send(f"{vm['name']} is not currently running.")

async def command_stop(message, args):
    if len(args) < 1 or args[0] not in vms.keys():
      await message.reply(f'Must specify one of: {configured_vms_str}')
      return

    vm = vms[args[0]]
    status = vm_power_state(vm)
    if status == 'starting':
        await message.reply(f"{vm['name']} is just starting")
    elif status =='deallocated' or status == 'stopped':
        await message.reply(f"{vm['name']} is already stopped")
    elif status == 'deallocating' or status == 'stopping':
        await message.reply(f"{vm['name']} is already stopping")
    else:
        await message.add_reaction(EYES)
        result = az_compute_client.virtual_machines.begin_deallocate(vm['az_resource_group'], vm['az_vm']).result()
        await message.remove_reaction(EYES, get_member())
        await message.add_reaction(CHECK)

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
    tokens = shlex.split(message.content)
    
    if len(tokens) > 1:
      command = tokens[1]
      args = tokens[2:]
      if command == 'help':
        await send_help_text(message, args)
      elif command == 'status':
        await command_status(message, args)
      elif command == 'start':
        await command_start(message, args)
      elif command == 'stop':
        await command_stop(message, args)
      elif command == 'restart':
        await command_restart(message, args)
    else:
      await send_help_text(message)

discord_client.run(discord_bot_token)
