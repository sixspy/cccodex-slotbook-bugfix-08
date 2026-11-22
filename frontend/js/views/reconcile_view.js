export const reconcileViewTemplate = `
  <div v-show="tab===4" class="panel">
    <h2>对账互证</h2>
    <p :class="recon.all_ok ? 'ok' : 'err'">{{ recon.all_ok ? '正式册全部同源' : '正式册存在分裂' }}</p>
    <p :class="recon.hold_audit_all_ok ? 'ok' : 'err'">
      占位-审计同态：{{ recon.hold_audit_all_ok ? '全部互证' : '存在缺审计占位' }}
    </p>
    <table>
      <thead>
        <tr><th>档</th><th>盘面已订</th><th>正式册席</th><th>占位中</th><th>已互证</th><th>结果</th><th>占位审计</th></tr>
      </thead>
      <tbody>
        <tr v-for="i in (recon.items||[])" :key="i.slot_code">
          <td>{{ i.slot_code }}</td><td>{{ i.slot_booked }}</td>
          <td>{{ i.booking_seats }}</td><td>{{ i.open_holds }}</td>
          <td>{{ i.proven_holds }}</td>
          <td :class="i.ok?'ok':'err'">{{ i.ok ? '通过' : '分裂' }}</td>
          <td :class="i.hold_audit_ok?'ok':'err'">{{ i.hold_audit_ok ? '同态' : '缺审计' }}</td>
        </tr>
      </tbody>
    </table>

    <h3>当事人互证</h3>
    <div>
      <input v-model="proofParty" placeholder="当事人 party_key" />
      <button class="ghost" @click="loadProof">互证查询</button>
    </div>
    <p class="err" v-if="actionErr">{{ actionErr }}</p>
    <div v-if="proof">
      <p :class="proof.all_holds_proven ? 'ok' : 'err'">
        占位 {{ proof.holds_total }} 笔，已互证 {{ proof.holds_proven }} 笔：
        {{ proof.all_holds_proven ? '全部同源' : '存在无审计占位' }}
      </p>
      <table>
        <thead><tr><th>类</th><th>ID</th><th>席/态</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="h in proof.holds" :key="'h'+h.id">
            <td>占位</td><td>{{ h.id }}</td><td>{{ h.seats }} / {{ h.status }}</td><td>expire {{ h.expire_at }}</td>
          </tr>
          <tr v-for="b in proof.bookings" :key="'b'+b.id">
            <td>正式册</td><td>{{ b.id }}</td><td>{{ b.seats }} / {{ b.status }}</td><td>快照代 {{ b.snapshot_gen }}</td>
          </tr>
          <tr v-for="w in proof.waitlist" :key="'w'+w.id">
            <td>候补</td><td>{{ w.id }}</td><td>{{ w.seats }} / {{ w.status }}</td><td>{{ w.reason }}</td>
          </tr>
        </tbody>
      </table>
      <h4>同源审计流水（{{ proof.audits.length }} 条）</h4>
      <table>
        <thead><tr><th>人</th><th>动作</th><th>明细</th><th>时</th></tr></thead>
        <tbody>
          <tr v-for="a in proof.audits" :key="a.id">
            <td>{{ a.actor }}</td><td>{{ a.action }}</td><td class="payload">{{ a.payload }}</td><td>{{ a.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
`;
