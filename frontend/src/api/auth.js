import { api } from './index'

export const authApi = {
  weworkRedirect() {
    return api.get('/api/auth/wework/redirect')
  },

  weworkCallback(code) {
    return api.get('/api/auth/wework/callback', { params: { code } })
  }
}