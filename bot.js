require('dotenv').config();
const {
  Client,
  GatewayIntentBits,
  Partials,
} = require('discord.js');

const config      = require('./config');
const queueSystem = require('./systems/queueSystem');
const audioSystem = require('./systems/audioSystem');
const dispatcher  = require('./systems/dispatcherSystem');

// ── Client ────────────────────────────────────────────────────────────────────

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMembers,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.DirectMessages,
  ],
  partials: [Partials.GuildMember, Partials.Channel, Partials.Message],
});

dispatcher.init(client);

// ── Ready ─────────────────────────────────────────────────────────────────────

client.once('ready', () => {
  console.log(`[Bot] Logged in as ${client.user.tag}`);
  console.log(`[Bot] Watching waiting room: ${config.WAITING_ROOM_ID}`);
});

// ── Voice state handler ───────────────────────────────────────────────────────

client.on('voiceStateUpdate', async (oldState, newState) => {
  const member = newState.member ?? oldState.member;
  if (!member || member.user.bot) return;

  const guild       = newState.guild ?? oldState.guild;
  const joinedWait  = newState.channelId === config.WAITING_ROOM_ID && oldState.channelId !== config.WAITING_ROOM_ID;
  const leftWait    = oldState.channelId === config.WAITING_ROOM_ID && newState.channelId !== config.WAITING_ROOM_ID;
  const leftSupport = config.SUPPORT_ROOM_IDS.includes(oldState.channelId) && !config.SUPPORT_ROOM_IDS.includes(newState.channelId ?? '');

  // ── User joins waiting room ──────────────────────────────────────────────────
  if (joinedWait) {
    queueSystem.add(member);
    console.log(`[Bot] ${member.displayName} joined waiting room — queue size: ${queueSystem.getAll().length}`);

    // Start waiting music in voice channel (random file, loops)
    const waitCh = guild.channels.cache.get(config.WAITING_ROOM_ID);
    if (waitCh && !audioSystem.isPlayingWaiting) {
      audioSystem.startWaiting(waitCh);
    }

    // Send DM with room selection + random audio file attachment
    await dispatcher.dispatch(guild, member);

    // Send a random audio file from /audio as DM so the user can listen
    const audioFile = audioSystem.getRandomFilePath();
    if (audioFile) {
      try {
        await member.send({
          content: '🎵 Hier ist etwas Musik für die Wartezeit:',
          files: [audioFile],
        });
      } catch (err) {
        console.error(`[Bot] Could not send audio DM to ${member.displayName}:`, err.message);
      }
    }
  }

  // ── User leaves waiting room ─────────────────────────────────────────────────
  if (leftWait) {
    const wasQueued = queueSystem.has(member.id);
    if (wasQueued) {
      queueSystem.remove(member.id);
      console.log(`[Bot] ${member.displayName} left waiting room — removed from queue.`);
    }

    // Stop music if waiting room is empty
    const waitCh = guild.channels.cache.get(config.WAITING_ROOM_ID);
    if (waitCh && waitCh.members.filter(m => !m.user.bot).size === 0) {
      audioSystem.stopWaiting();
    }
  }

  // ── User leaves a support room unexpectedly (not moved by bot) ───────────────
  if (leftSupport) {
    const activeRooms = dispatcher.getActiveRooms();
    const session     = activeRooms.get(oldState.channelId);
    if (session && session.userId === member.id) {
      console.log(`[Bot] ${member.displayName} left support room — ending session.`);
      await dispatcher.endSupportOnLeave(oldState.channelId);
    }
  }
});

// ── Interaction handler ───────────────────────────────────────────────────────

client.on('interactionCreate', async (interaction) => {
  try {
    // ── Button interactions ────────────────────────────────────────────────────
    if (interaction.isButton()) {
      const id = interaction.customId;

      if (id.startsWith('room_request:')) {
        await dispatcher.handleRoomSelect(interaction);

      } else if (id.startsWith('support_accept:')) {
        await dispatcher.handleSupportAccept(interaction);

      } else if (id.startsWith('support_decline:')) {
        await dispatcher.handleSupportDecline(interaction);

      } else if (id.startsWith('end_support:')) {
        await dispatcher.handleEndSupport(interaction);
      }
      return;
    }

    // ── Modal submissions ──────────────────────────────────────────────────────
    if (interaction.isModalSubmit()) {
      if (interaction.customId.startsWith('decline_modal:')) {
        await dispatcher.handleDeclineModal(interaction);
      }
      return;
    }

  } catch (err) {
    console.error('[Bot] Interaction error:', err);
    try {
      const reply = { content: '❌ Ein Fehler ist aufgetreten.', ephemeral: true };
      if (interaction.replied || interaction.deferred) {
        await interaction.followUp(reply);
      } else if (interaction.isButton() || interaction.isModalSubmit()) {
        await interaction.reply(reply);
      }
    } catch {}
  }
});

module.exports = { client };
