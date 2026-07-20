const {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  EmbedBuilder,
} = require('discord.js');
const config = require('../config');
const queueSystem = require('./queueSystem');
const audioSystem = require('./audioSystem');
const Session = require('../models/Session');
const Stats = require('../models/Stats');
const Settings = require('../models/Settings');

// roomId → session data
const activeRooms = new Map();
// citizenId → { timeout, guild, member, dmMsg }
const pendingCitizenSelections = new Map();
// `${citizenId}:${roomId}` → { timeout, guild, citizenId, supporterId, roomId, supporterDm }
const pendingSupportResponses = new Map();

let _client = null;
let _io = null;

function init(client, io) {
  _client = client;
  _io = io;
}

function emitRooms() {
  if (_io) _io.emit('roomsUpdate', getRoomStatuses());
}

function getRoomStatuses() {
  return config.SUPPORT_ROOM_IDS.map((id) => {
    const active = activeRooms.get(id) || null;
    return { roomId: id, active };
  });
}

async function getDispatchDelay() {
  const delay = await Settings.get('dispatchDelay', config.DISPATCH_DELAY);
  return Number(delay);
}

function hasSupporterOnline(guild) {
  for (const roomId of config.SUPPORT_ROOM_IDS) {
    const channel = guild.channels.cache.get(roomId);
    if (!channel) continue;
    if (channel.members.some((m) => m.roles.cache.has(config.SUPPORTER_ROLE_ID) && !m.user.bot))
      return true;
  }
  return false;
}

function findAvailableSupporterRoom(guild) {
  // Returns first room that has a supporter and no citizen — for random fallback
  for (const roomId of config.SUPPORT_ROOM_IDS) {
    if (activeRooms.has(roomId)) continue;
    const channel = guild.channels.cache.get(roomId);
    if (!channel) continue;
    const supporter = channel.members.find(
      (m) => m.roles.cache.has(config.SUPPORTER_ROLE_ID) && !m.user.bot
    );
    if (!supporter) continue;
    const hasCitizen = channel.members.some(
      (m) => m.roles.cache.has(config.BUERGER_ROLE_ID) && !m.user.bot
    );
    if (hasCitizen) continue;
    return { channel, supporter };
  }
  return null;
}

async function sendLog(guild, emoji, text) {
  try {
    const channel = guild.channels.cache.get(config.PING_CHANNEL_ID);
    if (channel) await channel.send(`${emoji} **${text}**`);
  } catch (err) {
    console.error('[Dispatcher] sendLog error:', err.message);
  }
}

// Core move logic — reused by all dispatch paths
async function moveCitizenToRoom(guild, citizen, supportRoom, supporter) {
  const queueEntries = await queueSystem.getAll();
  const entry = queueEntries.find((q) => q.userId === citizen.id);
  const waitTime = entry ? Date.now() - new Date(entry.joinedAt).getTime() : 0;

  await citizen.voice.setChannel(supportRoom);

  await supportRoom.permissionOverwrites.edit(guild.roles.everyone, { Connect: false });

  const sessionData = {
    roomId: supportRoom.id,
    supporterId: supporter.id,
    supporterName: supporter.user.username,
    citizenId: citizen.id,
    citizenName: citizen.user.username,
    waitTime,
    startedAt: new Date(),
    active: true,
  };
  activeRooms.set(supportRoom.id, sessionData);
  await Session.create(sessionData);

  await Stats.findOneAndUpdate(
    { supporterId: supporter.id },
    { supporterName: supporter.user.username, $inc: { totalSessions: 1 }, lastActive: new Date() },
    { upsert: true }
  );

  await queueSystem.remove(citizen.id);
  await sendLog(guild, '🟢', `Übernommen — ${citizen.user.username} → ${supporter.user.username}`);
  emitRooms();

  const count = await queueSystem.count();
  if (count === 0) audioSystem.stopWaiting();
}

// Random fallback dispatch (timeout or DM fail)
async function randomDispatch(guild, member) {
  try {
    await guild.members.fetch(member.id);
  } catch {}

  if (!member.voice?.channelId || member.voice.channelId !== config.WAITING_ROOM_ID) {
    await queueSystem.remove(member.id);
    return;
  }

  const available = findAvailableSupporterRoom(guild);
  if (!available) {
    await sendLog(guild, '🟠', `Kein freier Raum — ${member.user.username} wartet weiter`);
    return;
  }

  const { channel: supportRoom, supporter } = available;
  await moveCitizenToRoom(guild, member, supportRoom, supporter);
  await member.send(
    `✅ Du wurdest automatisch zu **${supportRoom.name}** (${supporter.user.username}) weitergeleitet.`
  ).catch(() => {});
}

// Builds the room selection embed + buttons for the citizen DM
function buildRoomSelectionDM(guild) {
  const embed = new EmbedBuilder()
    .setTitle('🎫 Support Raum Auswahl')
    .setDescription('Wähle einen Raum aus. Der Supporter kann deine Anfrage annehmen oder ablehnen.')
    .setColor(0x5865F2);

  const buttons = [];

  config.SUPPORT_ROOM_IDS.forEach((roomId, idx) => {
    const num = idx + 1;
    const channel = guild.channels.cache.get(roomId);

    if (!channel) {
      buttons.push(
        new ButtonBuilder()
          .setCustomId(`room_select:${roomId}`)
          .setLabel(`Support ${num} — Nicht gefunden`)
          .setStyle(ButtonStyle.Secondary)
          .setDisabled(true)
      );
      return;
    }

    const supporters = channel.members.filter(
      (m) => m.roles.cache.has(config.SUPPORTER_ROLE_ID) && !m.user.bot
    );
    const hasCitizen =
      activeRooms.has(roomId) ||
      channel.members.some((m) => m.roles.cache.has(config.BUERGER_ROLE_ID) && !m.user.bot);

    if (supporters.size === 0) {
      buttons.push(
        new ButtonBuilder()
          .setCustomId(`room_select:${roomId}`)
          .setLabel(`Support ${num} — Unbesetzt`)
          .setStyle(ButtonStyle.Secondary)
          .setDisabled(true)
      );
    } else if (hasCitizen) {
      buttons.push(
        new ButtonBuilder()
          .setCustomId(`room_select:${roomId}`)
          .setLabel(`Support ${num} — Besetzt`)
          .setStyle(ButtonStyle.Danger)
          .setDisabled(true)
      );
    } else {
      const names = supporters.map((m) => m.user.username).join(', ');
      buttons.push(
        new ButtonBuilder()
          .setCustomId(`room_select:${roomId}`)
          .setLabel(`Support ${num} — ${names}`.slice(0, 80))
          .setStyle(ButtonStyle.Success)
          .setDisabled(false)
      );
    }
  });

  // Max 5 buttons per row — we have exactly 5 rooms
  const row = new ActionRowBuilder().addComponents(buttons);
  return { embeds: [embed], components: [row] };
}

function disableAllButtons(components) {
  return components.map((row) => {
    const newRow = new ActionRowBuilder();
    newRow.addComponents(
      row.components.map((btn) =>
        ButtonBuilder.from(btn).setDisabled(true)
      )
    );
    return newRow;
  });
}

// Entry point: citizen joins waiting room
async function dispatch(guild, member) {
  const waitingChannel = guild.channels.cache.get(config.WAITING_ROOM_ID);

  if (!member.voice?.channelId || member.voice.channelId !== config.WAITING_ROOM_ID) {
    await queueSystem.remove(member.id);
    return;
  }

  if (!hasSupporterOnline(guild)) {
    await sendLog(guild, '⚫', `Niemand online — ${member.user.username} wartet`);
    if (waitingChannel) await audioSystem.playInChannel(waitingChannel, 'offline.mp3');
    return;
  }

  await sendLog(guild, '🟡', `Wartend — ${member.user.username}`);

  // Send room-selection DM to citizen
  const payload = buildRoomSelectionDM(guild);

  let dmMsg;
  try {
    dmMsg = await member.send(payload);
  } catch {
    // Can't DM → random dispatch immediately
    await randomDispatch(guild, member);
    return;
  }

  // 30-second timeout: citizen didn't choose
  const citizenTimeout = setTimeout(async () => {
    if (!pendingCitizenSelections.has(member.id)) return;
    pendingCitizenSelections.delete(member.id);
    await dmMsg.edit({ components: disableAllButtons(payload.components) }).catch(() => {});
    await member.send('⏱️ Zeit abgelaufen — du wirst automatisch zugeteilt.').catch(() => {});
    await randomDispatch(guild, member);
  }, 30_000);

  pendingCitizenSelections.set(member.id, {
    timeout: citizenTimeout,
    guild,
    member,
    dmMsg,
    components: payload.components,
  });
}

// Called when citizen clicks a room button (DM interaction)
async function handleRoomSelect(interaction) {
  const roomId = interaction.customId.split(':')[1];
  const citizenId = interaction.user.id;

  const pending = pendingCitizenSelections.get(citizenId);
  if (!pending) {
    await interaction.update({ content: '❌ Diese Auswahl ist abgelaufen.', embeds: [], components: [] }).catch(() => {});
    return;
  }

  clearTimeout(pending.timeout);
  pendingCitizenSelections.delete(citizenId);

  const { guild, member, components } = pending;

  // Disable citizen buttons
  await interaction.update({ components: disableAllButtons(components) }).catch(() => {});

  const channel = guild.channels.cache.get(roomId);
  if (!channel || activeRooms.has(roomId)) {
    await interaction.user.send('❌ Raum inzwischen besetzt — du wirst automatisch zugeteilt.').catch(() => {});
    await randomDispatch(guild, member);
    return;
  }

  const supportersInRoom = channel.members.filter(
    (m) => m.roles.cache.has(config.SUPPORTER_ROLE_ID) && !m.user.bot
  );
  if (supportersInRoom.size === 0) {
    await interaction.user.send('❌ Kein Supporter mehr im Raum — du wirst automatisch zugeteilt.').catch(() => {});
    await randomDispatch(guild, member);
    return;
  }

  // Pick random supporter from the chosen room
  const supporter = supportersInRoom.random();

  const acceptId = `support_accept:${citizenId}:${roomId}`;
  const declineId = `support_decline:${citizenId}:${roomId}`;

  const embed = new EmbedBuilder()
    .setTitle('📞 Neue Support-Anfrage')
    .setDescription(`**${interaction.user.username}** möchte von dir supportet werden.`)
    .setColor(0xFEE75C)
    .addFields({ name: 'Raum', value: channel.name });

  const row = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(acceptId).setLabel('✅ Annehmen').setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId(declineId).setLabel('❌ Ablehnen').setStyle(ButtonStyle.Danger)
  );

  let supporterDm;
  try {
    supporterDm = await supporter.send({ embeds: [embed], components: [row] });
  } catch {
    await interaction.user.send('⚠️ Supporter konnte nicht benachrichtigt werden — du wirst automatisch zugeteilt.').catch(() => {});
    await randomDispatch(guild, member);
    return;
  }

  await interaction.user.send(`⏳ Anfrage wurde an **${supporter.user.username}** gesendet — warte auf Antwort (30s)...`).catch(() => {});

  const disabledRow = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(acceptId).setLabel('✅ Annehmen').setStyle(ButtonStyle.Success).setDisabled(true),
    new ButtonBuilder().setCustomId(declineId).setLabel('❌ Ablehnen').setStyle(ButtonStyle.Danger).setDisabled(true)
  );

  // 30-second timeout: supporter didn't respond
  const supporterTimeout = setTimeout(async () => {
    const key = `${citizenId}:${roomId}`;
    if (!pendingSupportResponses.has(key)) return;
    pendingSupportResponses.delete(key);
    await supporterDm.edit({ components: [disabledRow] }).catch(() => {});
    await supporter.send('⏱️ Zeit abgelaufen — der Bürger wurde automatisch zugeteilt.').catch(() => {});
    await interaction.user.send('⏱️ Kein Supporter hat reagiert — du wirst automatisch zugeteilt.').catch(() => {});
    await randomDispatch(guild, member);
  }, 30_000);

  pendingSupportResponses.set(`${citizenId}:${roomId}`, {
    timeout: supporterTimeout,
    guild,
    member,
    supporterId: supporter.id,
    roomId,
    supporterDm,
    disabledRow,
  });
}

// Called when supporter clicks Accept or Decline (DM interaction)
async function handleSupportResponse(interaction, accepted) {
  const parts = interaction.customId.split(':');
  const citizenId = parts[1];
  const roomId = parts[2];
  const key = `${citizenId}:${roomId}`;

  const pending = pendingSupportResponses.get(key);
  if (!pending) {
    await interaction.update({ content: '❌ Diese Anfrage ist bereits abgelaufen.', components: [] }).catch(() => {});
    return;
  }

  clearTimeout(pending.timeout);
  pendingSupportResponses.delete(key);

  const { guild, member, disabledRow } = pending;

  // Disable supporter buttons
  await interaction.update({ components: [disabledRow] }).catch(() => {});

  if (accepted) {
    // Check citizen is still in waiting room
    try { await guild.members.fetch(member.id); } catch {}
    if (!member.voice?.channelId || member.voice.channelId !== config.WAITING_ROOM_ID) {
      await interaction.user.send('⚠️ Der Bürger ist nicht mehr im Warteraum.').catch(() => {});
      return;
    }

    const channel = guild.channels.cache.get(roomId);
    const supporter = guild.members.cache.get(pending.supporterId) ||
      await guild.members.fetch(pending.supporterId).catch(() => null);

    if (!channel || !supporter) {
      await interaction.user.send('❌ Fehler: Raum oder Supporter nicht gefunden.').catch(() => {});
      return;
    }

    try {
      await moveCitizenToRoom(guild, member, channel, supporter);
      await interaction.user.send(`✅ Du hast **${member.user.username}** angenommen.`).catch(() => {});
    } catch (err) {
      console.error('[Dispatcher] accept move error:', err.message);
      await interaction.user.send('❌ Fehler beim Verschieben.').catch(() => {});
    }
  } else {
    // Declined → inform citizen and random dispatch
    await interaction.user.send(
      `❌ Du hast die Anfrage von **${member.user.username}** abgelehnt.`
    ).catch(() => {});
    await member.send(
      '❌ Deine Anfrage wurde abgelehnt — du wirst automatisch zugeteilt.'
    ).catch(() => {});
    await randomDispatch(guild, member);
  }
}

async function endSupport(roomId, guild) {
  const session = activeRooms.get(roomId);
  if (!session) return null;

  try {
    const channel = guild.channels.cache.get(roomId);

    if (session.citizenId) {
      const citizen =
        guild.members.cache.get(session.citizenId) ||
        (await guild.members.fetch(session.citizenId).catch(() => null));
      if (citizen?.voice?.channelId === roomId) {
        await citizen.voice.disconnect().catch(() => {});
      }
    }

    if (channel) {
      await channel.permissionOverwrites.edit(guild.roles.everyone, { Connect: null });
    }

    const duration = Date.now() - new Date(session.startedAt).getTime();
    await Session.findOneAndUpdate(
      { roomId, supporterId: session.supporterId, active: true },
      { endedAt: new Date(), active: false }
    );
    await Stats.findOneAndUpdate(
      { supporterId: session.supporterId },
      { $inc: { totalTime: duration }, lastActive: new Date() }
    );

    activeRooms.delete(roomId);
    await sendLog(guild, '🔴', `Beendet — ${session.citizenName} (${Math.round(duration / 1000)}s)`);
    emitRooms();

    const next = await queueSystem.getNext();
    if (next) {
      const nextMember =
        guild.members.cache.get(next.userId) ||
        (await guild.members.fetch(next.userId).catch(() => null));
      if (nextMember) await dispatch(guild, nextMember);
    }

    return session;
  } catch (err) {
    console.error('[Dispatcher] endSupport error:', err.message);
    return null;
  }
}

function getActiveRooms() {
  return activeRooms;
}

module.exports = {
  init,
  dispatch,
  handleRoomSelect,
  handleSupportResponse,
  endSupport,
  getRoomStatuses,
  getActiveRooms,
  sendLog,
};
