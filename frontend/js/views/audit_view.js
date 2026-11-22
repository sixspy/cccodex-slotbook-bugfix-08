export const auditViewTemplate = `
  <div v-show="tab===5" class="panel">
    <h2>审计与争用</h2>
    <h3>争用</h3>
    <table>
      <thead><tr><th>锁</th><th>人</th><th>动作</th><th>详情</th><th>时</th></tr></thead>
      <tbody>
        <tr v-for="c in contention" :key="c.id">
          <td>{{ c.lock_key }}</td><td>{{ c.actor }}</td><td>{{ c.action }}</td>
          <td>{{ c.detail }}</td><td>{{ c.created_at }}</td>
        </tr>
        <tr v-if="!contention.length"><td colspan="5" class="muted">暂无争用痕</td></tr>
      </tbody>
    </table>
    <h3>审计流水（含 hold_create，不再过滤）</h3>
    <table>
      <thead><tr><th>人</th><th>动作</th><th>目标（当事人）</th><th>明细（档码/占位号/席）</th><th>时</th></tr></thead>
      <tbody>
        <tr v-for="a in audits" :key="a.id" :class="{ mark: a.action==='hold_create' }">
          <td>{{ a.actor }}</td><td>{{ a.action }}</td><td>{{ a.target }}</td>
          <td class="payload">{{ a.payload }}</td><td>{{ a.created_at }}</td>
        </tr>
      </tbody>
    </table>
  </div>
`;
