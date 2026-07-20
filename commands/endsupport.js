const { SlashCommandBuilder, MessageFlags } = require('discord.js');
const config = require('../config');
const dispatcher = require('../systems/dispatcherSystem');

module.exports = {
  data: new SlashCommandBuilder()
    .setName('endsupport')
    .setDescription('Beende den aktuellen Support-Fall in deinem Voice Channel'),

  async execute(interaction) {
    const member = interaction.member;

    // Check supporter role
    if (!member.roles.cache.has(config.SUPPORTER_ROLE_ID)) {
      return interaction.reply({
        content: '❌ Du hast keine Berechtigung diesen Befehl zu nutzen.',
        flags: MessageFlags.Ephemeral,
      });
    }

    // Check if supporter is in a voice channel
    const roomId = member.voice?.channelId;
    if (!roomId) {
      return interaction.reply({
        content: '❌ Du bist in keinem Voice Channel.',
        flags: MessageFlags.Ephemeral,
      });
    }

    // Check if it's one of the configured support rooms
    if (!config.SUPPORT_ROOM_IDS.includes(roomId)) {
      return interaction.reply({
        content: '❌ Du bist in keinem Support-Raum.',
        flags: MessageFlags.Ephemeral,
      });
    }

    // Check if there's actually a Bürger in the room (either via activeRooms or directly in channel)
    const activeRooms = dispatcher.getActiveRooms();
    const channel = interaction.guild.channels.cache.get(roomId);
    const hasBuerger = channel?.members.some(
      (m) => !m.user.bot && m.roles.cache.has(config.BUERGER_ROLE_ID)
    );
    const hasActiveSession = activeRooms.has(roomId);

    if (!hasBuerger && !hasActiveSession) {
      return interaction.reply({
        content: '❌ In diesem Raum ist kein aktiver Support-Fall.',
        flags: MessageFlags.Ephemeral,
      });
    }

    await interaction.deferReply({ flags: MessageFlags.Ephemeral });

    try {
      // If bot was restarted and activeRooms is empty, manually move Bürger out
      if (!hasActiveSession && hasBuerger) {
        const buerger = channel.members.find(
          (m) => !m.user.bot && m.roles.cache.has(config.BUERGER_ROLE_ID)
        );
        if (buerger) {
          const waitingChannel = interaction.guild.channels.cache.get(config.WAITING_ROOM_ID);
          if (waitingChannel) {
            await buerger.voice.setChannel(waitingChannel).catch(() => {});
          } else {
            await buerger.voice.disconnect().catch(() => {});
          }
        }
        await interaction.editReply({ content: '✅ Support beendet (manuell).' });
        return;
      }

      const result = await dispatcher.endSupport(roomId, interaction.guild);
      if (result) {
        await interaction.editReply({ content: '✅ Support erfolgreich beendet.' });
      } else {
        await interaction.editReply({ content: '⚠️ Fehler beim Beenden des Supports.' });
      }
    } catch (err) {
      console.error('[endsupport] Fehler:', err.message);
      await interaction.editReply({ content: '❌ Ein Fehler ist aufgetreten: ' + err.message });
    }
  },
};
