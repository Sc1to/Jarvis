// Resolves to /writer/api in production (base: '/writer') and /api in dev.
export const API = `${import.meta.env.BASE_URL}api`
