// In-memory queue — no database needed
const queue = new Map(); // userId -> entry

module.exports = {
  add(member) {
    if (!queue.has(member.id)) {
      queue.set(member.id, {
        userId:      member.id,
        username:    member.user.username,
        displayName: member.displayName,
        joinedAt:    new Date(),
      });
    }
  },

  remove(userId) {
    queue.delete(userId);
  },

  has(userId) {
    return queue.has(userId);
  },

  get(userId) {
    return queue.get(userId);
  },

  getAll() {
    return [...queue.values()];
  },

  clear() {
    queue.clear();
  },
};
