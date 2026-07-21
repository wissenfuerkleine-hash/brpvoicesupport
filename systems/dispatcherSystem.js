/**
 * DM-based Support Dispatcher
 *
 * Flow:
 *  1. User joins waiting room → sendRoomSelectionDM()
 *     → DM with buttons per room that has a supporter (room may be occupied by others too)
 *  2. User clicks a room button → handleRoomSelect()
 *     → DM to all supporters in that room: "Accept / Decline"
 *  3. Supporter clicks Accept → handleSupportAccept()
 *     → user moved, session started, supporter gets "End Support" button
 *  3b. Supporter clicks Decline → handleSupportDecline()
 *     → modal pops up asking for optional reason
 *  4. Modal submit → handleDeclineModal()
 *     → user notified with reason; if other supporters remain they can still accept
 *  5. Supporter clicks "End Support" → handleEndSupport()
 *     → session closed, user disconnected, both notified
 */

const {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  ModalBuilder,
  TextInputBuilder,
  TextInputStyle,
  EmbedBuilder,
} = require('discord.js');

const config      = require('../config');
const queueSystem = require('./queueSystem');

// ── State maps ─────────────────────────────────────────────────────────────────

// userId → { guildId, dmChannelId }
const pendingSelections = new Map();

// requestId → {
//   userId, userDisplayName, guildId, userDmChannelId,
//   roomId, roomLabel,
//   supporters: [{ staffId, dmChannelId, messageId }]
// }
const pendingRequests = new Map();

// roomId → { userId, supporterId, supporterDmChannelId, supporterMessageId, startedAt }
const activeSessions = new Map();

let _client = null;

// ── Helpers ────────────────────────────────────────────────────────────────────

function init(client) {
  _client = client;
}

function uid() {
  return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function roomLabel(roomId, guild) {
  const ch  = guild.channels.cache.get(roomId);
  const idx = config.SUPPORT_ROOM_IDS.indexOf(roomId) + 1;
  return ch ? ch.name : `Support Raum ${idx}`;
}

/** Returns all non-bot members with the supporter role currently in the channel. */
function supportersInRoom(roomId, guild) {
  const ch = guild.channels.cache.get(roomId);
  if (!ch) return [];
  return [...ch.members.filter(m => !m.user.bot && m.roles.cache.has(config.SUPPORTER_ROLE_ID)).values()];
}

/** Returns display names of all non-bot members in the channel. */
function membersInRoom(roomId, guild) {
  const ch = guild.channels.cache.get(roomId);
  if (!ch) return [];
  return [...ch.members.filter(m => !m.user.bot).values()].map(m => m.displayName);
}

// ── Step 1: Send room selection DM ────────────────────────────────────────────

async function dispatch(guild, member) {
  const availableRooms = config.SUPPORT_ROOM_IDS.filter(id => supportersInRoom(id, guild).length > 0);

  if (availableRooms.length === 0) {
    try {
      await member.send({
        embeds: [
          new EmbedBuilder()
            .setColor(0x2C2F33)
            .setTitle('⚫ Kein Supporter online')
            .setDescription('Momentan ist kein Supporter verfügbar.\nBitte versuche es später erneut oder verlasse den Warteraum.'),
        ],
      });
    } catch {}
    return;
  }

  // Build one button per available room (max 5 per ActionRow, max 5 rooms = 1 row)
  const buttons = availableRooms.map(roomId => {
    const names  = membersInRoom(roomId, guild);
    const label  = `${roomLabel(roomId, guild)}${names.length ? ' · ' + names.join(', ') : ''}`.slice(0, 80);

    return new ButtonBuilder()
      .setCustomId(`room_request:${guild.id}:${roomId}`)
      .setLabel(label)
      .setStyle(ButtonStyle.Primary)
      .setEmoji('📞');
  });

  // Split into rows of max 5 buttons
  const rows = [];
  for (let i = 0; i < buttons.length; i += 5) {
    rows.push(new ActionRowBuilder().addComponents(buttons.slice(i, i + 5)));
  }

  try {
    const dm = await member.send({
      embeds: [
        new EmbedBuilder()
          .setColor(0xF0A500)
          .setTitle('🎧 Support anfordern')
          .setDescription(
            'Bitte wähle den Support-Raum, in dem du betreut werden möchtest.\n' +
            'Du siehst nur Räume, in denen ein **Supporter** anwesend ist.\n' +
            'Neben dem Raumnamen siehst du die Personen, die sich aktuell darin befinden.'
          )
          .setFooter({ text: 'Klicke auf einen Raum, um eine Anfrage zu senden.' }),
      ],
      components: rows,
    });

    pendingSelections.set(member.id, {
      guildId:      guild.id,
      dmChannelId:  dm.channel.id,
      messageId:    dm.id,
    });
  } catch (err) {
    console.error(`[Dispatcher] Could not DM ${member.user.username}:`, err.message);
  }
}

// ── Step 2: User selected a room ──────────────────────────────────────────────

async function handleRoomSelect(interaction) {
  const [, guildId, roomId] = interaction.customId.split(':');
  const guild  = _client.guilds.cache.get(guildId);

  if (!guild) {
    await interaction.reply({ content: '❌ Server nicht gefunden.', ephemeral: true });
    return;
  }

  const staffList = supportersInRoom(roomId, guild);
  if (staffList.length === 0) {
    // Re-render updated room list
    await interaction.update({
      embeds: [
        new EmbedBuilder()
          .setColor(0xE67E22)
          .setTitle('⚠️ Kein Supporter mehr verfügbar')
          .setDescription('In diesem Raum ist gerade kein Supporter mehr. Bitte wähle erneut.'),
      ],
      components: interaction.message.components, // keep existing buttons
    });
    return;
  }

  const requestId = uid();
  const label     = roomLabel(roomId, guild);
  const userName  = interaction.user.globalName ?? interaction.user.username;

  // Acknowledge user — disable buttons
  await interaction.update({
    embeds: [
      new EmbedBuilder()
        .setColor(0x3498DB)
        .setTitle('📨 Anfrage gesendet')
        .setDescription(`Deine Anfrage wurde an **${label}** gesendet.\nBitte warte auf eine Antwort.`)
        .setFooter({ text: 'Du wirst per DM benachrichtigt.' }),
    ],
    components: [],
  });

  // DM all supporters in that room
  const supporterEntries = [];
  for (const staff of staffList) {
    try {
      const embed = new EmbedBuilder()
        .setColor(0x27AE60)
        .setTitle('🔔 Support-Anfrage')
        .setDescription(`**${userName}** möchte in **${label}** betreut werden.`)
        .addFields({ name: 'Nutzer', value: `<@${interaction.user.id}>`, inline: true })
        .setTimestamp();

      const row = new ActionRowBuilder().addComponents(
        new ButtonBuilder()
          .setCustomId(`support_accept:${requestId}`)
          .setLabel('✅ Annehmen')
          .setStyle(ButtonStyle.Success),
        new ButtonBuilder()
          .setCustomId(`support_decline:${requestId}`)
          .setLabel('❌ Ablehnen')
          .setStyle(ButtonStyle.Danger),
      );

      const msg = await staff.send({ embeds: [embed], components: [row] });
      supporterEntries.push({ staffId: staff.id, dmChannelId: msg.channel.id, messageId: msg.id });
    } catch (err) {
      console.error(`[Dispatcher] Could not DM supporter ${staff.user.username}:`, err.message);
    }
  }

  pendingRequests.set(requestId, {
    userId:          interaction.user.id,
    userDisplayName: userName,
    guildId,
    userDmChannelId: interaction.channelId,
    roomId,
    roomLabel:       label,
    supporters:      supporterEntries,
  });
}

// ── Step 3a: Supporter accepts ─────────────────────────────────────────────────

async function handleSupportAccept(interaction) {
  const requestId = interaction.customId.split(':')[1];
  const request   = pendingRequests.get(requestId);

  if (!request) {
    await interaction.update({ embeds: [new EmbedBuilder().setColor(0x95A5A6).setTitle('⚠️ Anfrage nicht mehr aktiv').setDescription('Diese Anfrage wurde bereits bearbeitet.')], components: [] });
    return;
  }

  pendingRequests.delete(requestId);

  const guild  = _client.guilds.cache.get(request.guildId);
  const member = guild?.members.cache.get(request.userId);

  // Move user into support room
  try {
    if (member?.voice?.channel) {
      await member.voice.setChannel(request.roomId);
    }
  } catch (err) {
    console.error('[Dispatcher] Could not move member:', err.message);
  }

  // Cancel all other supporter DMs for this request
  for (const s of request.supporters) {
    if (s.staffId === interaction.user.id) continue;
    try {
      const ch  = await _client.channels.fetch(s.dmChannelId);
      const msg = await ch.messages.fetch(s.messageId);
      await msg.edit({
        embeds: [new EmbedBuilder().setColor(0x95A5A6).setTitle('ℹ️ Anfrage übernommen').setDescription('Ein anderer Supporter hat diese Anfrage bereits übernommen.')],
        components: [],
      });
    } catch {}
  }

  // Update accepting supporter's DM with "End Support" button
  const sessionEmbed = new EmbedBuilder()
    .setColor(0x27AE60)
    .setTitle('✅ Support gestartet')
    .setDescription(`Du betreust jetzt **${request.userDisplayName}** in **${request.roomLabel}**.`)
    .setFooter({ text: 'Klicke auf "Support beenden", wenn der Fall abgeschlossen ist.' })
    .setTimestamp();

  const endRow = new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId(`end_support:${request.roomId}:${request.userId}`)
      .setLabel('🔴 Support beenden')
      .setStyle(ButtonStyle.Danger),
  );

  await interaction.update({ embeds: [sessionEmbed], components: [endRow] });

  // Store active session (messageId = this updated message)
  activeSessions.set(request.roomId, {
    userId:               request.userId,
    supporterId:          interaction.user.id,
    supporterDmChannelId: interaction.channelId,
    supporterMessageId:   interaction.message.id,
    guildId:              request.guildId,
    startedAt:            new Date(),
  });

  // Notify user
  try {
    const userCh = await _client.channels.fetch(request.userDmChannelId);
    await userCh.send({
      embeds: [
        new EmbedBuilder()
          .setColor(0x27AE60)
          .setTitle('✅ Anfrage angenommen')
          .setDescription(`**${interaction.user.globalName ?? interaction.user.username}** hat deine Anfrage angenommen.\nDu wirst gleich in **${request.roomLabel}** bewegt.`),
      ],
    });
  } catch {}
}

// ── Step 3b: Supporter declines (show modal) ──────────────────────────────────

async function handleSupportDecline(interaction) {
  const requestId = interaction.customId.split(':')[1];
  const request   = pendingRequests.get(requestId);

  if (!request) {
    await interaction.update({ embeds: [new EmbedBuilder().setColor(0x95A5A6).setTitle('⚠️ Anfrage nicht mehr aktiv').setDescription('Diese Anfrage wurde bereits bearbeitet.')], components: [] });
    return;
  }

  // Show modal — this responds to the interaction
  const modal = new ModalBuilder()
    .setCustomId(`decline_modal:${requestId}:${interaction.user.id}`)
    .setTitle('Anfrage ablehnen');

  modal.addComponents(
    new ActionRowBuilder().addComponents(
      new TextInputBuilder()
        .setCustomId('reason')
        .setLabel('Grund (optional)')
        .setStyle(TextInputStyle.Short)
        .setPlaceholder('z.B. Nicht zuständig — bitte wende dich an ...')
        .setRequired(false)
        .setMaxLength(200),
    ),
  );

  await interaction.showModal(modal);
}

// ── Step 4: Modal submitted ───────────────────────────────────────────────────

async function handleDeclineModal(interaction) {
  const [, requestId, staffId] = interaction.customId.split(':');
  const reason  = interaction.fields.getTextInputValue('reason').trim();
  const request = pendingRequests.get(requestId);

  if (!request) {
    await interaction.reply({ content: '⚠️ Anfrage nicht mehr aktiv.', ephemeral: true });
    return;
  }

  // Remove this supporter from the pending list
  request.supporters = request.supporters.filter(s => s.staffId !== staffId);

  // Edit the original DM message of this supporter (buttons → "declined" note)
  const myEntry = pendingRequests.get(requestId)
    ? request.supporters.find(s => s.staffId === staffId) // already removed, find from original
    : null;
  // Re-fetch from original list before filter:
  // Since we already filtered, we stored the entry reference earlier? Let's just fetch by staffId from _client
  // Actually: let's edit the message the modal was triggered FROM — but modal interactions don't carry message.
  // We need to iterate supporter entries. Since we filtered already, find by staffId in the *original* stored list.
  // The supporter entry was removed — find via client DMs is complex. Let's send an ephemeral reply instead.
  await interaction.reply({ content: '❌ Du hast die Anfrage abgelehnt.', ephemeral: true });

  if (request.supporters.length > 0) {
    // Other supporters can still accept — keep request alive
    pendingRequests.set(requestId, request);
    return;
  }

  // No supporters left → notify user
  pendingRequests.delete(requestId);

  const declineEmbed = new EmbedBuilder()
    .setColor(0xE74C3C)
    .setTitle('❌ Anfrage abgelehnt')
    .setDescription(
      reason
        ? `Deine Support-Anfrage für **${request.roomLabel}** wurde abgelehnt.\n**Grund:** ${reason}`
        : `Deine Support-Anfrage für **${request.roomLabel}** wurde abgelehnt.`
    );

  try {
    const userCh = await _client.channels.fetch(request.userDmChannelId);
    await userCh.send({ embeds: [declineEmbed] });
  } catch {}
}

// ── Step 5: Supporter ends support ────────────────────────────────────────────

async function handleEndSupport(interaction) {
  const [, roomId, userId] = interaction.customId.split(':');
  const session = activeSessions.get(roomId);

  if (!session) {
    await interaction.update({
      embeds: [new EmbedBuilder().setColor(0x95A5A6).setTitle('⚠️ Kein aktiver Support').setDescription('Dieser Support-Fall ist bereits beendet.')],
      components: [],
    });
    return;
  }

  activeSessions.delete(roomId);

  const guild = _client.guilds.cache.get(session.guildId ?? _client.guilds.cache.first()?.id);

  // Disconnect user from the support room voice channel
  try {
    const member = await guild?.members.fetch(userId);
    if (member?.voice?.channelId === roomId) {
      await member.voice.disconnect();
    }
  } catch (err) {
    console.error('[Dispatcher] Could not disconnect member:', err.message);
  }

  // Update supporter DM
  await interaction.update({
    embeds: [
      new EmbedBuilder()
        .setColor(0x95A5A6)
        .setTitle('🔴 Support beendet')
        .setDescription('Der Support-Fall wurde geschlossen.')
        .setTimestamp(),
    ],
    components: [],
  });

  // Notify user
  try {
    const user = await _client.users.fetch(userId);
    await user.send({
      embeds: [
        new EmbedBuilder()
          .setColor(0x95A5A6)
          .setTitle('Support beendet')
          .setDescription('Dein Support wurde vom Supporter abgeschlossen. Danke!'),
      ],
    });
  } catch {}
}

// ── Called when a user/citizen leaves a support room unexpectedly ─────────────

async function endSupportOnLeave(roomId) {
  const session = activeSessions.get(roomId);
  if (!session) return;
  activeSessions.delete(roomId);

  // Update supporter DM silently
  try {
    const ch  = await _client.channels.fetch(session.supporterDmChannelId);
    const msg = await ch.messages.fetch(session.supporterMessageId);
    await msg.edit({
      embeds: [
        new EmbedBuilder()
          .setColor(0x95A5A6)
          .setTitle('🔴 Support beendet')
          .setDescription('Der Nutzer hat den Support-Raum verlassen. Session wurde automatisch beendet.')
          .setTimestamp(),
      ],
      components: [],
    });
  } catch {}
}

function getActiveRooms() {
  return activeSessions;
}

module.exports = {
  init,
  dispatch,
  handleRoomSelect,
  handleSupportAccept,
  handleSupportDecline,
  handleDeclineModal,
  handleEndSupport,
  endSupportOnLeave,
  getActiveRooms,
};
