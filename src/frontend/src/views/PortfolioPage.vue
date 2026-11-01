<template>
  <div
    class="portfolio-page"
    data-test="portfolio-page"
  >
    <div
      v-if="loading"
      class="portfolio-loading"
    >
      <el-icon
        class="is-loading portfolio-loading__icon"
        aria-hidden="true"
      >
        <Loading />
      </el-icon>
      <span>{{ t('common.loading') }}</span>
    </div>

    <template v-else>
      <nav
        class="portfolio-view-switch"
        role="group"
        :aria-label="t('portfolio.viewModeLabel')"
      >
        <button
          type="button"
          data-test="portfolio-mode-legacy"
          :aria-pressed="viewMode === 'legacy'"
          @click="setViewMode('legacy')"
        >
          {{ t('portfolio.viewLegacy') }}
        </button>
        <button
          type="button"
          data-test="portfolio-mode-composition"
          :aria-pressed="viewMode === 'composition'"
          @click="setViewMode('composition')"
        >
          {{ t('portfolio.viewComposition') }}
        </button>
      </nav>

      <section
        v-if="viewMode === 'composition'"
        class="portfolio-composition"
        data-test="portfolio-composition-view"
        :aria-label="t('portfolio.compositionTitle')"
      >
        <header class="portfolio-composition__header">
          <div>
            <span class="portfolio-kicker">{{ t('portfolio.compositionKicker') }}</span>
            <h1>{{ t('portfolio.compositionTitle') }}</h1>
            <p>{{ t('portfolio.compositionDescription') }}</p>
          </div>
          <button
            type="button"
            class="portfolio-composition__refresh"
            data-test="portfolio-composition-refresh"
            :disabled="compositionListLoading || compositionProjectionLoading"
            @click="loadData"
          >
            {{ t('portfolio.btnRefresh') }}
          </button>
          <button
            type="button"
            class="portfolio-composition__refresh"
            data-test="portfolio-import-source-open"
            @click="openImportedSourceDialog"
          >
            {{ t('portfolio.importSourceOpen') }}
          </button>
        </header>

        <section
          v-if="showImportedSourceDialog"
          class="portfolio-composition__section portfolio-import-source-dialog"
          role="dialog"
          aria-modal="true"
          :aria-label="t('portfolio.importSourceTitle')"
          data-test="portfolio-import-source-dialog"
        >
          <header class="portfolio-composition__header">
            <div>
              <h2>{{ t('portfolio.importSourceTitle') }}</h2>
              <p>{{ t('portfolio.importSourceDisclaimer') }}</p>
            </div>
            <button
              type="button"
              class="portfolio-composition__refresh"
              data-test="portfolio-import-source-close"
              :disabled="sourceImportBusy"
              @click="showImportedSourceDialog = false"
            >
              {{ t('portfolio.importSourceClose') }}
            </button>
          </header>

          <div class="portfolio-import-source-dialog__existing">
            <label for="portfolio-existing-import-source">
              {{ t('portfolio.importSourceExisting') }}
            </label>
            <select
              id="portfolio-existing-import-source"
              v-model="selectedImportVersionId"
              data-test="portfolio-existing-import-source"
              :disabled="existingImportsLoading || existingImportSources.length === 0"
            >
              <option value="">
                {{ t('portfolio.importSourceExistingPlaceholder') }}
              </option>
              <option
                v-for="source in existingImportSources"
                :key="source.import_version_id"
                :value="source.import_version_id"
                :disabled="source.source_material_status !== 'verified'"
              >
                {{ source.portfolio_name }} · {{ source.import_version_id }} ·
                {{ source.source_material_status === 'verified'
                  ? `${source.imported_count} ${t('portfolio.importSourceRows')}`
                  : importSourceArtifactStatusLabel(source.source_material_status) }}
              </option>
            </select>
            <button
              type="button"
              class="portfolio-composition__refresh"
              data-test="portfolio-import-source-attach"
              :disabled="sourceImportBusy || !selectedImportSource"
              @click="attachExistingImportSource"
            >
              {{ t('portfolio.importSourceAttach') }}
            </button>
            <button
              v-if="existingImportSourcesHasMore"
              type="button"
              class="portfolio-composition__refresh"
              data-test="portfolio-import-source-load-more"
              :disabled="existingImportsLoading"
              @click="loadMoreImportedSources"
            >
              {{ t('portfolio.compositionLoadMore') }}
            </button>
          </div>

          <form
            class="portfolio-import-source-form"
            data-test="portfolio-import-source-form"
            @submit.prevent="importTransactionsAsComposition"
          >
            <fieldset :disabled="sourceImportBusy || Boolean(pendingImportVersionId)">
              <label>
                {{ t('portfolio.importSourcePortfolioName') }}
                <input
                  v-model="importPortfolioName"
                  data-test="portfolio-import-source-name"
                  maxlength="200"
                  required
                >
              </label>
              <label>
                {{ t('portfolio.importSourcePortfolioRef') }}
                <input
                  v-model="importPortfolioRef"
                  data-test="portfolio-import-source-ref"
                  maxlength="128"
                  required
                >
              </label>
              <label>
                {{ t('portfolio.importSourceBaseCurrency') }}
                <input
                  v-model="importBaseCurrency"
                  data-test="portfolio-import-source-base-currency"
                  maxlength="16"
                  required
                >
              </label>
              <label>
                {{ t('portfolio.importSourceAsOf') }}
                <input
                  v-model="importSourceAsOf"
                  data-test="portfolio-import-source-as-of"
                  type="date"
                >
              </label>
              <label>
                {{ t('portfolio.importSourceCurrency') }}
                <input
                  v-model="importSourceCurrency"
                  data-test="portfolio-import-source-currency"
                  maxlength="16"
                >
              </label>
              <label class="portfolio-import-source-form__rows">
                {{ t('portfolio.importSourceJsonRows') }}
                <textarea
                  v-model="importTransactionsJson"
                  data-test="portfolio-import-source-rows"
                  rows="8"
                  required
                />
              </label>
            </fieldset>
            <p class="portfolio-import-source-form__hint">
              {{ t('portfolio.importSourceMissingMetadata') }}
            </p>
            <p
              v-if="sourceImportError"
              class="portfolio-composition__error"
              role="alert"
              data-test="portfolio-import-source-error"
            >
              {{ sourceImportError }}
            </p>
            <button
              type="submit"
              class="portfolio-composition__refresh"
              data-test="portfolio-import-source-submit"
              :disabled="sourceImportBusy"
            >
              {{ sourceImportBusy ? t('portfolio.querying') : t('portfolio.importSourceSubmit') }}
            </button>
          </form>
        </section>

        <div class="portfolio-composition__selector">
          <label for="portfolio-composition-version">
            {{ t('portfolio.compositionSelectVersion') }}
          </label>
          <select
            id="portfolio-composition-version"
            v-model="selectedCompositionKey"
            data-test="portfolio-composition-version-select"
            :disabled="compositionListLoading || compositionVersions.length === 0"
            @change="loadCompositionProjection"
          >
            <option
              value=""
              disabled
            >
              {{ t('portfolio.compositionSelectPlaceholder') }}
            </option>
            <option
              v-for="version in compositionVersions"
              :key="compositionVersionKey(version)"
              :value="compositionVersionKey(version)"
            >
              {{ version.portfolio_ref }} · v{{ version.membership_version }} ·
              {{ compositionSourceLabel(version.source_type) }}
            </option>
          </select>
          <button
            v-if="compositionHasMore"
            type="button"
            data-test="portfolio-composition-load-more"
            :disabled="compositionListLoading"
            @click="loadMoreCompositionVersions"
          >
            {{ compositionListLoading ? t('portfolio.querying') : t('portfolio.compositionLoadMore') }}
          </button>
        </div>

        <p
          v-if="compositionError"
          class="portfolio-composition__error"
          role="alert"
          data-test="portfolio-composition-error"
        >
          {{ compositionError }}
        </p>
        <p
          v-else-if="compositionListLoading"
          class="portfolio-composition__status"
          role="status"
        >
          {{ t('portfolio.querying') }}
        </p>
        <p
          v-else-if="compositionVersions.length === 0"
          class="portfolio-composition__status"
          data-test="portfolio-composition-empty"
        >
          {{ t('portfolio.compositionEmpty') }}
        </p>
        <p
          v-else-if="compositionProjectionLoading"
          class="portfolio-composition__status"
          role="status"
        >
          {{ t('portfolio.querying') }}
        </p>
        <p
          v-else-if="compositionListChanged"
          class="portfolio-composition__status"
          role="status"
          data-test="portfolio-composition-list-changed"
        >
          {{ t('portfolio.compositionListChanged') }}
        </p>

        <template v-if="compositionProjection">
          <p
            v-if="compositionProjection.source_status === 'adapter_not_integrated'"
            class="portfolio-composition__unavailable"
            role="status"
            data-test="portfolio-composition-adapter-unavailable"
          >
            {{ t('portfolio.compositionAdapterUnavailable') }}
          </p>
          <dl class="portfolio-composition__facts">
            <div>
              <dt>{{ t('portfolio.compositionSource') }}</dt>
              <dd data-test="portfolio-composition-source">
                {{ compositionSourceLabel(compositionProjection.source_type) }}
              </dd>
            </div>
            <div>
              <dt>{{ t('portfolio.compositionSourceStatus') }}</dt>
              <dd data-test="portfolio-composition-source-status">
                {{ compositionStatusLabel(compositionProjection.source_status) }}
              </dd>
            </div>
            <div>
              <dt>{{ t('portfolio.compositionAccountTotal') }}</dt>
              <dd data-test="portfolio-composition-account-total">
                {{ compositionAmount(compositionProjection.account_total.value, compositionProjection.account_total.currency) }}
              </dd>
            </div>
            <div>
              <dt>{{ t('portfolio.compositionCoverage') }}</dt>
              <dd data-test="portfolio-composition-coverage">
                {{ compositionProjection.coverage.complete
                  ? t('portfolio.compositionCoverageComplete')
                  : t('portfolio.compositionCoverageIncomplete') }}
                <code v-if="compositionProjection.coverage.code">
                  {{ t('portfolio.compositionDiagnosticCode') }}:
                  {{ compositionProjection.coverage.code }}
                </code>
              </dd>
            </div>
            <div>
              <dt>{{ t('portfolio.compositionCreditability') }}</dt>
              <dd data-test="portfolio-composition-creditability">
                {{ t('portfolio.compositionDisplayOnly') }}
              </dd>
            </div>
            <div>
              <dt>{{ t('portfolio.compositionOverlap') }}</dt>
              <dd data-test="portfolio-composition-overlap">
                {{ t('portfolio.compositionNonAdditive') }}
              </dd>
            </div>
          </dl>

          <section
            v-if="compositionProjection.source_facts?.kind === 'asset_research_reports'"
            class="portfolio-composition__section"
            data-test="portfolio-research-facts"
          >
            <h2>{{ t('portfolio.compositionResearchFacts') }}</h2>
            <p data-test="portfolio-research-disclaimer">
              {{ t('portfolio.compositionResearchDisclaimer') }}
            </p>
            <ul>
              <li
                v-for="(artifact, index) in compositionProjection.source_facts.artifacts || []"
                :key="`${artifact.report_content_hash || artifact.status}-${index}`"
                data-test="portfolio-research-artifact"
              >
                <p>
                  {{ t('portfolio.compositionResearchArtifactStatus') }}:
                  {{ compositionResearchArtifactStatusLabel(artifact.status) }}
                </p>
                <template v-if="artifact.status === 'available'">
                  <p>
                    {{ t('portfolio.compositionResearchIdentity') }}:
                    {{ artifact.asset_type }} · {{ artifact.canonical_id }}
                  </p>
                  <p>
                    {{ t('portfolio.compositionResearchReportIntegrity') }}:
                    {{ compositionResearchIntegrityLabel(artifact.report_integrity_status) }}
                  </p>
                  <p>
                    {{ t('portfolio.compositionResearchReportCreated') }}:
                    {{ artifact.report_created_at || t('portfolio.compositionUnavailable') }}
                  </p>
                  <p>
                    {{ t('portfolio.compositionResearchFreshness') }}:
                    {{ t('portfolio.compositionResearchFreshnessUndefined') }}
                  </p>
                  <p>
                    {{ t('portfolio.compositionResearchCurrency') }}:
                    {{ t('portfolio.compositionResearchCurrencyUndeclared') }}
                  </p>
                  <p v-if="artifact.published_decision">
                    {{ t('portfolio.compositionResearchDecision') }}:
                    {{ artifact.published_decision.market_view }} ·
                    {{ artifact.published_decision.recommendation }} ·
                    {{ artifact.published_decision.actionability }}
                  </p>
                  <p v-else>
                    {{ t('portfolio.compositionResearchDecisionUnavailable') }}
                  </p>
                </template>
              </li>
            </ul>
          </section>

          <section
            v-if="compositionProjection.source_facts?.kind === 'portfolio_ledger_import_versions'"
            class="portfolio-composition__section"
            data-test="portfolio-imported-source-facts"
          >
            <h2>{{ t('portfolio.importSourceFacts') }}</h2>
            <p data-test="portfolio-import-source-disclaimer">
              {{ t('portfolio.importSourceProjectionDisclaimer') }}
            </p>
            <ul>
              <li
                v-for="(artifact, index) in compositionProjection.source_facts.artifacts"
                :key="`${artifact.import_version_id || artifact.status}-${index}`"
                data-test="portfolio-import-source-artifact"
              >
                <p>{{ t('portfolio.importSourceArtifactStatus') }}: {{ importSourceArtifactStatusLabel(artifact.status) }}</p>
                <template v-if="artifact.status === 'available'">
                  <p>{{ t('portfolio.importSourcePortfolioName') }}: {{ artifact.portfolio_name }}</p>
                  <p>{{ t('portfolio.importSourceId') }}: {{ artifact.import_version_id }}</p>
                  <p>{{ t('portfolio.importSourceAsOf') }}: {{ artifact.source_as_of || t('portfolio.importSourceUnknown') }}</p>
                  <p>{{ t('portfolio.importSourceCurrency') }}: {{ artifact.source_currency || t('portfolio.importSourceUnknown') }}</p>
                  <p>{{ t('portfolio.importSourceIntegrity') }}: {{ artifact.source_integrity_status }}</p>
                  <p>{{ t('portfolio.importSourceHash') }}: <code>{{ artifact.source_sha256 }}</code></p>
                  <p>{{ t('portfolio.importSourceRows') }}: {{ artifact.source_row_count }}</p>
                  <p>
                    {{ t('portfolio.importSourceDateCoverage') }}:
                    {{ artifact.trade_date_rows_present }}/{{ artifact.source_row_count }} ·
                    {{ importSourceDateCoverageLabel(artifact.trade_date_coverage) }}
                  </p>
                  <p>{{ t('portfolio.importSourceFreshness') }}: {{ t('portfolio.importSourceFreshnessUndefined') }}</p>
                  <button
                    type="button"
                    class="portfolio-composition__refresh"
                    :data-test="`portfolio-import-source-detail-${artifact.import_version_id}`"
                    :disabled="importedSourceLoadingId === artifact.import_version_id"
                    @click="loadImportedSourceDetail(artifact.import_version_id || '')"
                  >
                    {{ importedSourceLoadingId === artifact.import_version_id
                      ? t('portfolio.querying')
                      : t('portfolio.importSourceShowRaw') }}
                  </button>
                  <pre
                    v-if="importedSourceDetails[artifact.import_version_id || '']"
                    class="portfolio-import-source-raw"
                    :data-test="`portfolio-import-source-raw-${artifact.import_version_id}`"
                  >{{ JSON.stringify(importedSourceDetails[artifact.import_version_id || '']?.source_document?.transactions, null, 2) }}</pre>
                </template>
              </li>
            </ul>
            <p
              v-if="importedSourceDetailError"
              class="portfolio-composition__error"
              role="alert"
              data-test="portfolio-import-source-detail-error"
            >
              {{ importedSourceDetailError }}
            </p>
          </section>

          <section class="portfolio-composition__section">
            <h2>{{ t('portfolio.compositionAttribution') }}</h2>
            <p data-test="portfolio-composition-attribution-status">
              {{ compositionAttributionStatusLabel(compositionProjection.strategy_attribution.status) }}
            </p>
            <p>
              {{ t('portfolio.compositionAttributedValue') }}:
              <strong data-test="portfolio-composition-attributed-value">
                {{ compositionAmount(compositionProjection.strategy_attribution.attributed_value, compositionProjection.base_currency) }}
              </strong>
            </p>
            <p>
              {{ t('portfolio.compositionResidual') }}:
              <strong data-test="portfolio-composition-residual">
                {{ compositionAmount(compositionProjection.strategy_attribution.unattributed_account_value, compositionProjection.base_currency) }}
              </strong>
            </p>
            <p>{{ t('portfolio.compositionResidualBasis') }}</p>
            <ul v-if="compositionProjection.strategies.length > 0">
              <li
                v-for="strategy in compositionProjection.strategies"
                :key="strategy.strategy_ref"
              >
                {{ strategy.strategy_ref }} —
                {{ compositionAmount(strategy.attributed_value, compositionProjection.base_currency) }}
                ({{ compositionAttributionStatusLabel(strategy.attribution_status) }})
              </li>
            </ul>
          </section>

          <section class="portfolio-composition__section">
            <h2>{{ t('portfolio.compositionAccountMembers') }}</h2>
            <p
              v-if="compositionProjection.market_valuation"
              data-test="portfolio-market-valuation-summary"
            >
              行情输入 / Market inputs:
              {{ compositionProjection.market_valuation.status }}
              · positions {{ compositionProjection.market_valuation.position_count }}
              · market event skew {{ compositionProjection.market_valuation.market_event_skew_ns ?? '未建立 / Not established' }} ns
              · reconciliation {{ compositionProjection.market_valuation.reconciliation_status }}
              · market facts do not alter account totals, cash, credit, or admission.
            </p>
            <p
              v-if="compositionProjection.provider_snapshot_consistency"
              data-test="portfolio-provider-snapshot-consistency"
            >
              授权账户快照偏差 / Authorized account snapshot skew:
              {{ compositionProjection.provider_snapshot_consistency.status }}
              · coverage {{ compositionProjection.provider_snapshot_consistency.coverage_status }}
              · {{ compositionProjection.provider_snapshot_consistency.skew_ns ?? '未建立 / Not established' }} ns
              · {{ compositionProjection.provider_snapshot_consistency.skew_policy }}
            </p>
            <p v-if="compositionProjection.accounts.length === 0">
              {{ t('portfolio.compositionNoAccountMembers') }}
            </p>
            <ul v-else>
              <li
                v-for="account in compositionProjection.accounts"
                :key="account.member_ref"
              >
                {{ account.member_ref }} — {{ compositionAmount(account.value, account.currency) }}
                <span data-test="portfolio-composition-account-quality">
                  ({{ account.quality }})
                </span>
                <span v-if="account.duplicate_of_ref">
                  ({{ t('portfolio.compositionDuplicateOf', { ref: account.duplicate_of_ref }) }})
                </span>
                <span v-if="!account.included_in_total">
                  ({{ t('portfolio.compositionNotIncluded') }})
                </span>
                <span
                  v-if="account.detail_code"
                  data-test="portfolio-composition-account-detail-code"
                >
                  {{ t('portfolio.compositionDiagnosticCode') }}:
                  <code>{{ account.detail_code }}</code>
                </span>
                <details
                  v-if="account.provider_observation"
                  data-test="portfolio-provider-account-observation"
                >
                  <summary>
                    授权账户事实 / Authorized provider facts:
                    {{ account.provider_observation.status }}
                  </summary>
                  <p
                    v-if="account.provider_observation.status === 'absent'
                      || account.provider_observation.status === 'unavailable'"
                  >
                    {{ account.provider_observation.code }}
                  </p>
                  <template
                    v-else-if="account.provider_observation.status === 'available'
                      || account.provider_observation.status === 'stale'"
                  >
                    <dl data-test="portfolio-provider-account-cut">
                      <div>
                        <dt>观测质量 / Observation quality</dt>
                        <dd>{{ account.provider_observation.quality }}</dd>
                      </div>
                      <div>
                        <dt>Provider observation</dt>
                        <dd><code>{{ account.provider_observation.observation_id }}</code></dd>
                      </div>
                      <div>
                        <dt>Session generation / cursor</dt>
                        <dd>
                          <code>{{ account.provider_observation.session_generation ?? '缺失 / Missing' }}</code>
                          · {{ account.provider_observation.cursor ?? '缺失 / Missing' }}
                        </dd>
                      </div>
                      <div>
                        <dt>一致性 / Consistency</dt>
                        <dd>
                          {{ account.provider_observation.consistency }}
                          · {{ account.provider_observation.consistency === 'multi_query'
                            ? '原子性未建立 / atomicity not established'
                            : 'Provider atomic' }}
                        </dd>
                      </div>
                      <div>
                        <dt>独立 cut / Independent cut</dt>
                        <dd>
                          <code>{{ account.provider_observation.cut.started_at_utc }}</code>
                          → <code>{{ account.provider_observation.cut.completed_at_utc }}</code>
                        </dd>
                      </div>
                      <div>
                        <dt>行时间偏差 / Row time spread</dt>
                        <dd>
                          {{ account.provider_observation.cut.row_skew_ns ?? '未建立 / Not established' }} ns
                          · {{ account.provider_observation.cut.row_observed_at_count }}/{{ account.provider_observation.cut.row_count }}
                        </dd>
                      </div>
                      <div>
                        <dt>覆盖完整性 / Coverage</dt>
                        <dd>
                          {{ account.provider_observation.coverage.state }}
                          · balances {{ account.provider_observation.coverage.balances_complete ? '完整 / complete' : '不完整 / incomplete' }}
                          · positions {{ account.provider_observation.coverage.positions_complete ? '完整 / complete' : '不完整 / incomplete' }}
                        </dd>
                      </div>
                    </dl>
                    <p data-test="portfolio-provider-account-reconciliation">
                      账户观察与执行账簿为独立来源；未声明已对账。
                      / Provider account facts and execution books are independent sources; reconciliation is not established.
                    </p>
                    <p>账户估值来源数值 / Provider account valuation (unconverted)</p>
                    <p v-if="account.provider_observation.valuation">
                      {{ compositionAmount(
                        account.provider_observation.valuation.available_cash,
                        account.provider_observation.valuation.currency,
                      ) }} available ·
                      {{ compositionAmount(
                        account.provider_observation.valuation.equity,
                        account.provider_observation.valuation.currency,
                      ) }} equity ·
                      <code>{{ account.provider_observation.valuation.observed_at_utc }}</code>
                    </p>
                    <p v-else>估值字段缺失 / Provider valuation missing.</p>
                    <p>逐币种余额（不换汇）/ Balances by original currency (no FX conversion)</p>
                    <ul data-test="portfolio-provider-account-balances">
                      <li
                        v-for="(balance, index) in account.provider_observation.balances"
                        :key="`${balance.resource.product_type}/${balance.resource.margin_pool}/${balance.currency}/${index}`"
                      >
                        {{ balance.resource.product_type }}/{{ balance.resource.margin_pool }}
                        · {{ balance.currency }}
                        · total {{ compositionAmount(balance.total, balance.currency) }}
                        · available {{ compositionAmount(balance.available, balance.currency) }}
                        · locked {{ compositionAmount(balance.locked, balance.currency) }}
                        · <code>{{ balance.observed_at_utc }}</code>
                      </li>
                      <li v-if="account.provider_observation.balances.length === 0">
                        余额行缺失 / No balance rows reported.
                      </li>
                    </ul>
                    <p>Provider 持仓（均价不是 mark）/ Provider positions (average price is not a mark)</p>
                    <ul data-test="portfolio-provider-account-positions">
                      <li
                        v-for="(position, index) in account.provider_observation.positions"
                        :key="`${position.instrument.provider}/${position.instrument.venue}/${position.instrument.environment}/${position.instrument.product_type}/${position.instrument.instrument_id}/${position.side}/${index}`"
                      >
                        <code>
                          {{ position.instrument.provider }}/{{ position.instrument.venue }}/{{ position.instrument.environment }}/{{ position.instrument.product_type }}/{{ position.instrument.instrument_id }} · {{ position.instrument.native_symbol }}
                        </code>
                        · crosswalk {{ position.valuation_binding?.binding_ref ?? 'missing' }}@{{ position.valuation_binding?.binding_version ?? 'unknown' }}
                        · {{ position.resource.product_type }}/{{ position.resource.margin_pool }}
                        · {{ position.side }} {{ position.quantity }} {{ position.qty_unit }}
                        · average {{ compositionAmount(position.average_price, position.price_currency) }}
                        · <code>{{ position.observed_at_utc }}</code>
                        · mark {{ portfolioValuationInputText(position.valuation_inputs.mark_price) }}
                        · multiplier {{ portfolioValuationInputText(position.valuation_inputs.contract_multiplier) }}
                        · FX {{ portfolioValuationInputText(position.valuation_inputs.fx_rate) }}
                        · market value {{ position.valuation_inputs.market_value.status }}
                        <details
                          v-if="position.valuation_inputs.market_cut"
                          data-test="portfolio-market-input-cut"
                        >
                          <summary>行情独立 cut / Independent market cut</summary>
                          <p>
                            account position {{ position.valuation_inputs.market_cut.account_position_observed_at_utc ?? 'missing' }}
                            · market event {{ position.valuation_inputs.market_cut.market_event_at_utc ?? 'missing' }}
                            · skew {{ position.valuation_inputs.market_cut.account_to_market_skew_ns ?? '未建立 / Not established' }} ns
                            · cursor {{ position.valuation_inputs.market_cut.cursor_available ? 'available' : 'missing' }}
                            · coverage {{ position.valuation_inputs.market_cut.coverage?.status ?? '未建立 / Not established' }}
                            ({{ position.valuation_inputs.market_cut.coverage?.accepted_event_count ?? '—' }}/{{ position.valuation_inputs.market_cut.coverage?.expected_event_count ?? '—' }} accepted, {{ position.valuation_inputs.market_cut.coverage?.missing_event_count ?? '—' }} missing)
                            · query {{ position.valuation_inputs.market_cut.query_id ?? 'missing' }}
                            · identity metadata {{ position.valuation_inputs.market_cut.identity_metadata_version }}
                            · knowledge cutoff {{ position.valuation_inputs.market_cut.knowledge_cutoff_utc ?? 'missing' }}
                          </p>
                          <p>
                            available {{ position.valuation_inputs.mark_price.available_at_utc ?? 'missing' }}
                            · committed {{ position.valuation_inputs.mark_price.committed_at_utc ?? 'missing' }}
                            · revision {{ position.valuation_inputs.mark_price.revision_id ?? 'missing' }}
                          </p>
                        </details>
                        <details
                          v-if="position.valuation_inputs.fx_market_cut"
                          data-test="portfolio-fx-input-cut"
                        >
                          <summary>汇率独立 cut / FX input cut</summary>
                          <p>
                            account position {{ position.valuation_inputs.fx_market_cut.account_position_observed_at_utc ?? 'missing' }}
                            · FX event {{ position.valuation_inputs.fx_market_cut.market_event_at_utc ?? 'missing' }}
                            · skew {{ position.valuation_inputs.fx_market_cut.account_to_market_skew_ns ?? '未建立 / Not established' }} ns
                            · cursor {{ position.valuation_inputs.fx_market_cut.cursor_available ? 'available' : 'missing' }}
                            · coverage {{ position.valuation_inputs.fx_market_cut.coverage?.status ?? '未建立 / Not established' }}
                            ({{ position.valuation_inputs.fx_market_cut.coverage?.accepted_event_count ?? '—' }}/{{ position.valuation_inputs.fx_market_cut.coverage?.expected_event_count ?? '—' }} accepted, {{ position.valuation_inputs.fx_market_cut.coverage?.missing_event_count ?? '—' }} missing)
                            · query {{ position.valuation_inputs.fx_market_cut.query_id ?? 'missing' }}
                            · identity metadata {{ position.valuation_inputs.fx_market_cut.identity_metadata_version }}
                            · knowledge cutoff {{ position.valuation_inputs.fx_market_cut.knowledge_cutoff_utc ?? 'missing' }}
                          </p>
                          <p>
                            available {{ position.valuation_inputs.fx_rate.available_at_utc ?? 'missing' }}
                            · committed {{ position.valuation_inputs.fx_rate.committed_at_utc ?? 'missing' }}
                            · revision {{ position.valuation_inputs.fx_rate.revision_id ?? 'missing' }}
                          </p>
                        </details>
                      </li>
                      <li v-if="account.provider_observation.positions.length === 0">
                        持仓行缺失 / No position rows reported.
                      </li>
                    </ul>
                    <p>
                      估值仅供展示，缺少 mark、合约乘数或 FX 时不计算市值；不进入现金、授信或交易准入。
                      / Display only: no market value is calculated without a mark, contract multiplier, and FX fact; these facts do not affect cash, credit, or admission.
                    </p>
                  </template>
                  <p v-else data-test="portfolio-provider-observation-unsupported">
                    Unsupported provider observation state.
                  </p>
                </details>
              </li>
            </ul>
          </section>

          <section
            v-if="compositionProjection.source_type === 'live' && compositionProjection.account_book_sources?.length"
            class="portfolio-composition__section"
            data-test="portfolio-account-book-sources"
          >
            <h2>{{ t('portfolio.compositionExecutionBooks') }}</h2>
            <p>{{ t('portfolio.compositionExecutionBooksDisclaimer') }}</p>
            <article
              v-for="source in compositionProjection.account_book_sources"
              :key="source.account_ref"
              class="portfolio-composition__execution-book"
              data-test="portfolio-account-book-source"
            >
              <h3>{{ t('portfolio.compositionExecutionAccount') }}: {{ source.account_ref }}</h3>
              <dl>
                <div>
                  <dt>{{ t('portfolio.compositionExecutionState') }}</dt>
                  <dd>{{ source.state }}</dd>
                </div>
                <div data-test="portfolio-account-book-coverage">
                  <dt>{{ t('portfolio.compositionCoverage') }}</dt>
                  <dd>
                    {{ source.coverage.complete
                      ? t('portfolio.compositionCoverageComplete')
                      : t('portfolio.compositionCoverageIncomplete') }}
                    · {{ t('portfolio.compositionExecutionCursor') }}
                    {{ source.coverage.baseline_execution_cursor }} →
                    {{ source.coverage.current_execution_cursor }}
                  </dd>
                </div>
                <div v-if="source.coverage.reasons.length > 0">
                  <dt>{{ t('portfolio.compositionExecutionCoverageReasons') }}</dt>
                  <dd>{{ source.coverage.reasons.join(', ') }}</dd>
                </div>
              </dl>

              <section
                class="portfolio-composition__financial"
                data-test="portfolio-account-book-financial"
              >
                <h4>持久财务账簿 / Persisted financial books</h4>
                <p>
                  持久执行账簿资金与成本仅作账簿投影，不是实时账户总额，也不会加入账户总额。
                  / Persisted execution-ledger cash and cost are a book projection, not live account equity, and are not added to the account total.
                </p>
                <p
                  v-if="!source.financial || source.financial.status === 'absent'"
                  data-test="portfolio-account-book-financial-absent"
                >
                  财务子投影未提供 / Financial projection not provided.
                </p>
                <p
                  v-else-if="source.financial.status === 'unavailable'"
                  data-test="portfolio-account-book-financial-unavailable"
                >
                  {{ t('portfolio.compositionUnavailable') }}
                  · {{ source.financial.code }}
                  · {{ source.financial.freshness }}
                  · {{ source.financial.cut_relationship }}
                </p>
                <template v-else>
                  <dl data-test="portfolio-account-book-financial-cut">
                    <div>
                      <dt>财务账簿状态 / Financial state</dt>
                      <dd>{{ source.financial.state }}</dd>
                    </div>
                    <div>
                      <dt>账簿投影完整 / Projection complete</dt>
                      <dd>{{ source.financial.complete ? '是 / Yes' : '否 / No' }}</dd>
                    </div>
                    <div>
                      <dt>独立账簿 cut / Independent ledger cut</dt>
                      <dd>{{ source.financial.cut_relationship }}</dd>
                    </div>
                    <div>
                      <dt>新鲜度 / Freshness</dt>
                      <dd>{{ source.financial.freshness }}</dd>
                    </div>
                    <div>
                      <dt>采集时间（纳秒）/ Captured at (ns)</dt>
                      <dd><code>{{ source.financial.ledger_cut.captured_at_ns }}</code></dd>
                    </div>
                    <div>
                      <dt>Owner directory revision</dt>
                      <dd><code>{{ source.financial.ledger_cut.owner_directory_revision }}</code></dd>
                    </div>
                  </dl>
                  <ul data-test="portfolio-account-book-financial-watermarks">
                    <li
                      v-for="watermark in source.financial.ledger_cut.watermarks"
                      :key="watermark.source_kind"
                    >
                      {{ watermark.source_kind }} · {{ watermark.source_ref }}
                      · <code>{{ watermark.generation }}</code>
                      · cursor {{ watermark.cursor }}
                      · as of <code>{{ watermark.as_of_ns }} ns</code>
                    </li>
                  </ul>
                  <article
                    v-for="book in source.financial.books"
                    :key="`${book.owner.kind}/${book.owner.owner_ref}`"
                    data-test="portfolio-account-book-financial-owner"
                  >
                    <h5>{{ book.owner.kind }}/{{ book.owner.owner_ref }}</h5>
                    <p>现金 / Cash</p>
                    <ul
                      v-if="book.cash.length > 0"
                      data-test="portfolio-account-book-financial-cash"
                    >
                      <li
                        v-for="amount in book.cash"
                        :key="amount.currency"
                      >
                        {{ compositionAmount(amount.amount, amount.currency) }}
                      </li>
                    </ul>
                    <p v-else>未报告现金条目 / No cash rows reported.</p>
                    <p>持仓成本 / Position cost basis</p>
                    <ul v-if="book.positions.length > 0">
                      <li
                        v-for="position in book.positions"
                        :key="position.instrument"
                        data-test="portfolio-account-book-financial-position"
                      >
                        {{ position.instrument }} · quantity {{ position.quantity }}
                        · cost basis
                        {{ position.cost_basis === null
                          ? '缺失 / Missing'
                          : compositionAmount(position.cost_basis, position.cost_currency) }}
                        · {{ position.cost_method }} / {{ position.product_model }}
                        · metadata {{ position.metadata_version }}
                      </li>
                    </ul>
                    <p v-else>未报告持仓成本 / No position costs reported.</p>
                    <p>累计费用 / Cumulative fees</p>
                    <ul
                      v-if="book.cumulative_fees.length > 0"
                      data-test="portfolio-account-book-financial-fees"
                    >
                      <li
                        v-for="amount in book.cumulative_fees"
                        :key="amount.currency"
                      >
                        {{ compositionAmount(amount.amount, amount.currency) }}
                      </li>
                    </ul>
                    <p v-else>未报告费用条目 / No fee rows reported.</p>
                    <p>已实现盈亏 / Realized PnL</p>
                    <ul v-if="book.realized_pnl.length > 0">
                      <li
                        v-for="amount in book.realized_pnl"
                        :key="amount.currency"
                      >
                        {{ compositionAmount(amount.amount, amount.currency) }}
                      </li>
                    </ul>
                    <p v-else>未报告盈亏条目 / No realized PnL rows reported.</p>
                    <p>
                      成本基础完整 / Cost basis complete:
                      {{ book.cost_basis_complete ? '是 / Yes' : '否 / No' }}
                    </p>
                  </article>
                  <section data-test="portfolio-account-book-financial-unallocated">
                    <h5>未分配财务账 / Unallocated financial book</h5>
                    <p>现金 / Cash</p>
                    <ul v-if="source.financial.unallocated.cash.length > 0">
                      <li
                        v-for="amount in source.financial.unallocated.cash"
                        :key="amount.currency"
                      >
                        {{ compositionAmount(amount.amount, amount.currency) }}
                      </li>
                    </ul>
                    <p v-else>未报告现金条目 / No cash rows reported.</p>
                    <p>持仓数量 / Position quantities</p>
                    <ul v-if="source.financial.unallocated.positions.length > 0">
                      <li
                        v-for="position in source.financial.unallocated.positions"
                        :key="position.instrument"
                      >
                        {{ position.instrument }} · {{ position.quantity }}
                      </li>
                    </ul>
                    <p v-else>未报告持仓 / No positions reported.</p>
                    <p>费用 / Fees</p>
                    <ul v-if="source.financial.unallocated.fees.length > 0">
                      <li
                        v-for="amount in source.financial.unallocated.fees"
                        :key="amount.currency"
                      >
                        {{ compositionAmount(amount.amount, amount.currency) }}
                      </li>
                    </ul>
                    <p v-else>未报告费用条目 / No fee rows reported.</p>
                  </section>
                </template>
              </section>

              <section
                v-if="source.unallocated_book"
                data-test="portfolio-account-book-unallocated"
              >
                <h4>
                  {{ t('portfolio.compositionUnallocatedBook') }}
                  · {{ source.unallocated_book.owner_kind }}/{{ source.unallocated_book.owner_ref }}
                </h4>
                <p>{{ t('portfolio.compositionCurrentUnallocatedPositions') }}</p>
                <ul v-if="source.unallocated_book.current_positions.length > 0">
                  <li
                    v-for="position in source.unallocated_book.current_positions"
                    :key="position.instrument"
                    data-test="portfolio-account-book-unallocated-position"
                  >
                    {{ position.instrument }} · {{ position.net_quantity }}
                  </li>
                </ul>
                <p v-else>
                  {{ t('portfolio.compositionNoExecutionFacts') }}
                </p>
                <p>{{ t('portfolio.compositionUnallocatedFees') }}</p>
                <ul v-if="source.unallocated_book.fees_since_baseline.length > 0">
                  <li
                    v-for="fee in source.unallocated_book.fees_since_baseline"
                    :key="fee.currency"
                    data-test="portfolio-account-book-unallocated-fee"
                  >
                    {{ fee.amount }} {{ fee.currency }}
                  </li>
                </ul>
                <p v-else>
                  {{ t('portfolio.compositionNoExecutionFacts') }}
                </p>
              </section>
              <p
                v-else
                data-test="portfolio-account-book-unallocated-unavailable"
              >
                {{ t('portfolio.compositionUnallocatedUnavailable') }}
              </p>

              <div data-test="portfolio-account-book-provider-change">
                <h4>{{ t('portfolio.compositionProviderPositionChange') }}</h4>
                <ul v-if="source.provider_position_change.length > 0">
                  <li
                    v-for="position in source.provider_position_change"
                    :key="position.instrument"
                  >
                    {{ position.instrument }} · {{ position.net_quantity }}
                  </li>
                </ul>
                <p v-else>
                  {{ t('portfolio.compositionNoExecutionFacts') }}
                </p>
              </div>

              <div data-test="portfolio-account-book-position-residual">
                <h4>{{ t('portfolio.compositionPositionResidual') }}</h4>
                <ul v-if="source.position_residual.length > 0">
                  <li
                    v-for="position in source.position_residual"
                    :key="position.instrument"
                  >
                    {{ position.instrument }} · {{ position.net_quantity }}
                  </li>
                </ul>
                <p v-else>
                  {{ t('portfolio.compositionNoExecutionFacts') }}
                </p>
              </div>

              <div data-test="portfolio-account-book-fee-residual">
                <h4>{{ t('portfolio.compositionFeeResidual') }}</h4>
                <ul v-if="source.fee_residual.length > 0">
                  <li
                    v-for="fee in source.fee_residual"
                    :key="fee.currency"
                  >
                    {{ fee.amount }} {{ fee.currency }}
                  </li>
                </ul>
                <p v-else>
                  {{ t('portfolio.compositionNoExecutionFacts') }}
                </p>
              </div>
            </article>
          </section>
        </template>
        <PortfolioAnalyticsTaskPanel
          v-if="selectedCompositionVersion"
          :portfolio-ref="selectedCompositionVersion.portfolio_ref"
          :membership-version="selectedCompositionVersion.membership_version"
          :source-type="selectedCompositionVersion.source_type"
        />
      </section>

      <section
        v-if="viewMode === 'legacy'"
        class="portfolio-hero"
        data-test="portfolio-hero"
      >
        <div class="portfolio-hero__copy">
          <span class="portfolio-kicker">{{ t('portfolio.heroKicker') }}</span>
          <h1>{{ t('portfolio.heroTitle') }}</h1>
          <p>
            {{ t('portfolio.heroSubtitle', { running: runningWorkspaces.length }) }}
          </p>
          <div class="portfolio-hero__badges">
            <span
              v-for="badge in heroBadges"
              :key="badge.label"
              class="portfolio-badge"
            >
              <span>{{ badge.label }}</span>
              <strong>{{ badge.value }}</strong>
            </span>
          </div>
        </div>

        <div class="portfolio-hero__status">
          <span class="portfolio-status-chip">
            <span class="portfolio-status-dot" />
            {{ portfolioHealthLabel }}
          </span>
          <div class="portfolio-hero__asset">
            <span>{{ t('portfolio.cardTotalAssets') }}</span>
            <strong>{{ formatMoney(overview.total_assets) }}</strong>
          </div>
          <div
            class="portfolio-hero__pnl"
            :class="signedValueClass(overview.total_pnl)"
          >
            {{ formatSignedMoney(overview.total_pnl) }}
            <span>{{ formatSignedPercent(overview.total_pnl_pct) }}</span>
          </div>
          <el-button
            class="portfolio-refresh"
            :icon="Refresh"
            @click="loadData"
          >
            {{ t('portfolio.btnRefresh') }}
          </el-button>
        </div>
      </section>

      <section
        v-if="viewMode === 'legacy'"
        class="portfolio-overview"
        data-test="portfolio-overview"
        :aria-label="t('portfolio.overviewTitle')"
      >
        <article
          v-for="card in summaryCards"
          :key="card.label"
          class="portfolio-metric"
          :class="'portfolio-metric--' + card.tone"
        >
          <span class="portfolio-metric__icon">
            <el-icon aria-hidden="true">
              <component :is="card.icon" />
            </el-icon>
          </span>
          <span class="portfolio-metric__label">{{ card.label }}</span>
          <strong :class="card.valueClass">{{ card.value }}</strong>
          <small>{{ card.helper }}</small>
        </article>
      </section>

      <section
        v-if="viewMode === 'legacy'"
        class="portfolio-layout"
      >
        <section
          class="portfolio-workbench"
          data-test="portfolio-workbench"
        >
          <div class="portfolio-panel-heading portfolio-panel-heading--inline">
            <div>
              <span class="portfolio-kicker">{{ t('portfolio.workbenchKicker') }}</span>
              <h2>{{ t('portfolio.workbenchTitle') }}</h2>
              <p>{{ t('portfolio.workbenchDesc') }}</p>
            </div>
          </div>

          <el-tabs
            v-model="activeTab"
            class="portfolio-tabs"
          >
            <el-tab-pane
              :label="t('portfolio.tabWorkspaces')"
              name="workspaces"
            >
              <div class="portfolio-tab-panel">
                <div class="portfolio-section-heading">
                  <h3>{{ t('portfolio.tabWorkspaces') }}</h3>
                  <span>{{ t('portfolio.workspacesDesc') }}</span>
                </div>
                <el-table
                  :data="runningWorkspaces"
                  stripe
                  size="small"
                  class="portfolio-table"
                >
                  <el-table-column
                    prop="name"
                    :label="t('portfolio.colWorkspaceName')"
                    min-width="180"
                  />
                  <el-table-column
                    :label="t('portfolio.colStatus')"
                    width="110"
                    align="center"
                  >
                    <template #default="{ row }">
                      <el-tag
                        :type="row.status === 'running' ? 'success' : row.status === 'error' ? 'danger' : 'info'"
                        size="small"
                      >
                        {{ workspaceStatusLabel(row.status) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column
                    prop="unit_count"
                    :label="t('portfolio.colWorkspaceUnits')"
                    width="130"
                    align="right"
                  />
                </el-table>
              </div>
            </el-tab-pane>

            <el-tab-pane
              :label="t('portfolio.tabPositions')"
              name="positions"
            >
              <div class="portfolio-tab-panel">
                <div class="portfolio-section-heading">
                  <h3>{{ t('portfolio.tabPositions') }}</h3>
                  <span>{{ t('portfolio.positionsDesc') }}</span>
                </div>

                <div
                  v-if="isTabLoading('positions')"
                  class="portfolio-querying"
                >
                  <el-icon
                    class="is-loading"
                    aria-hidden="true"
                  >
                    <Loading />
                  </el-icon>
                  <span>{{ t('portfolio.querying') }}</span>
                </div>
                <template v-else>
                  <div
                    v-if="positions.length > 0"
                    class="portfolio-exposure-grid"
                  >
                    <article
                      v-for="card in positionMetricCards"
                      :key="card.label"
                      class="portfolio-exposure-card"
                    >
                      <span>{{ card.label }}</span>
                      <strong :class="card.valueClass">{{ card.value }}</strong>
                    </article>
                  </div>
                  <div
                    v-if="positions.length === 0"
                    class="portfolio-empty"
                  >
                    <el-icon aria-hidden="true">
                      <Operation />
                    </el-icon>
                    <span>{{ t('portfolio.emptyPositions') }}</span>
                  </div>
                  <el-table
                    v-else
                    :data="positions"
                    stripe
                    size="small"
                    class="portfolio-table"
                  >
                    <el-table-column
                      prop="strategy_name"
                      :label="t('portfolio.colStrategy')"
                      min-width="180"
                    />
                    <el-table-column
                      prop="data_name"
                      :label="t('portfolio.colSymbol')"
                      width="120"
                    />
                    <!-- @vue-generic {PositionItem} -->
                    <el-table-column
                      :label="t('portfolio.colDirection')"
                      width="90"
                      align="center"
                    >
                      <template #default="{ row }">
                        <el-tag
                          :type="positionDirectionTag(row)"
                          size="small"
                        >
                          {{ directionLabel(row.direction) }}
                        </el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colLongPosition')"
                      width="100"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatPositionSize(row.long_position) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colShortPosition')"
                      width="100"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatPositionSize(row.short_position) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colSize')"
                      width="100"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatPositionSize(row.size) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colCostPrice')"
                      width="110"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatNumber(row.price, 4) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colLatestPrice')"
                      width="110"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatNumber(row.latest_price ?? row.price, 4) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colMarketValue')"
                      width="130"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatMoney(row.market_value) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colPositionPnl')"
                      width="120"
                      align="right"
                    >
                      <template #default="{ row }">
                        <span :class="signedValueClass(row.position_pnl || 0)">
                          {{ formatSignedMoney(row.position_pnl || 0) }}
                        </span>
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colMarginValue')"
                      width="110"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatOptionalMoney(row.margin_value) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('workspaceDialogs.leverage')"
                      width="90"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatNumber(row.leverage, 2) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colCommission')"
                      width="100"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ formatNumber(row.commission, 2) }}
                      </template>
                    </el-table-column>
                    <!-- @vue-generic {PositionItem} -->
                    <el-table-column
                      :label="t('portfolio.colValuationStatus')"
                      width="130"
                      align="center"
                    >
                      <template #default="{ row }">
                        <el-tooltip
                          :content="valuationTooltip(row)"
                          placement="top"
                        >
                          <el-tag
                            :type="valuationStatusTag(row)"
                            size="small"
                          >
                            {{ valuationStatusLabel(row) }}
                          </el-tag>
                        </el-tooltip>
                      </template>
                    </el-table-column>
                    <el-table-column
                      prop="updated_at"
                      :label="t('portfolio.colUpdatedAt')"
                      width="160"
                    >
                      <template #default="{ row }">
                        {{ formatDateTime(row.updated_at) }}
                      </template>
                    </el-table-column>
                  </el-table>
                </template>
              </div>
            </el-tab-pane>

            <el-tab-pane
              :label="t('portfolio.tabTrades')"
              name="trades"
            >
              <div class="portfolio-tab-panel">
                <div class="portfolio-section-heading">
                  <h3>{{ t('portfolio.tabTrades') }}</h3>
                  <span>{{ t('portfolio.tradesDesc') }}</span>
                </div>
                <div
                  v-if="isTabLoading('trades')"
                  class="portfolio-querying"
                >
                  <el-icon
                    class="is-loading"
                    aria-hidden="true"
                  >
                    <Loading />
                  </el-icon>
                  <span>{{ t('portfolio.querying') }}</span>
                </div>
                <template v-else>
                  <div
                    v-if="trades.length === 0"
                    class="portfolio-empty"
                  >
                    <el-icon aria-hidden="true">
                      <DataLine />
                    </el-icon>
                    <span>{{ t('portfolio.emptyTrades') }}</span>
                  </div>
                  <el-table
                    v-else
                    :data="trades"
                    stripe
                    size="small"
                    class="portfolio-table"
                    max-height="500"
                  >
                    <el-table-column
                      prop="strategy_name"
                      :label="t('portfolio.colStrategy')"
                      min-width="180"
                    />
                    <el-table-column
                      prop="data_name"
                      :label="t('portfolio.colSymbolShort')"
                      width="100"
                    />
                    <el-table-column
                      :label="t('portfolio.colDirection')"
                      width="80"
                      align="center"
                    >
                      <template #default="{ row }">
                        <span :class="tradeDirectionClass(row.direction)">
                          {{ tradeDirectionLabel(row.direction) }}
                        </span>
                      </template>
                    </el-table-column>
                    <el-table-column
                      prop="dtopen"
                      :label="t('portfolio.colOpenDate')"
                      width="160"
                    />
                    <el-table-column
                      prop="dtclose"
                      :label="t('portfolio.colCloseDate')"
                      width="160"
                    />
                    <el-table-column
                      :label="t('portfolio.colPrice')"
                      width="100"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ row.price.toFixed(2) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colSizeShort')"
                      width="80"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ row.size }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colCommission')"
                      width="100"
                      align="right"
                    >
                      <template #default="{ row }">
                        {{ row.commission.toFixed(2) }}
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colNetPnl')"
                      width="120"
                      align="right"
                      sortable
                    >
                      <template #default="{ row }">
                        <span :class="row.pnlcomm >= 0 ? 'text-green-600' : 'text-red-600'">
                          {{ row.pnlcomm >= 0 ? '+' : '' }}{{ row.pnlcomm.toFixed(2) }}
                        </span>
                      </template>
                    </el-table-column>
                    <el-table-column
                      :label="t('portfolio.colHoldingDays')"
                      prop="barlen"
                      width="100"
                      align="center"
                    />
                  </el-table>
                </template>
              </div>
            </el-tab-pane>

            <el-tab-pane
              :label="t('portfolio.tabEquity')"
              name="equity"
            >
              <div
                v-if="activeTab === 'equity'"
                class="portfolio-tab-panel"
              >
                <div class="portfolio-section-heading portfolio-section-heading--chart">
                  <div>
                    <h3>{{ t('portfolio.tabEquity') }}</h3>
                    <span>{{ t('portfolio.equityDesc') }}</span>
                  </div>
                  <el-select
                    v-if="equityData?.strategies.length"
                    v-model="selectedEquitySeries"
                    class="portfolio-equity-selector"
                    size="small"
                    :placeholder="t('portfolio.equitySelectorPlaceholder')"
                  >
                    <el-option
                      value="portfolio"
                      :label="t('portfolio.seriesTotalEquity')"
                    />
                    <el-option
                      v-for="strategy in equityData.strategies"
                      :key="strategy.instance_id"
                      :value="strategy.instance_id"
                      :label="strategy.strategy_name"
                    />
                  </el-select>
                </div>
                <div
                  v-if="isTabLoading('equity')"
                  class="portfolio-querying"
                >
                  <el-icon
                    class="is-loading"
                    aria-hidden="true"
                  >
                    <Loading />
                  </el-icon>
                  <span>{{ t('portfolio.querying') }}</span>
                </div>
                <div
                  v-else-if="selectedEquityCurve.values.length === 0"
                  class="portfolio-empty"
                >
                  <el-icon aria-hidden="true">
                    <DataLine />
                  </el-icon>
                  <span>{{ t('portfolio.emptyEquity') }}</span>
                </div>
                <div
                  v-else
                  class="portfolio-chart-stack"
                >
                  <div
                    ref="pnlChartRef"
                    class="portfolio-chart portfolio-chart--pnl"
                  />
                  <div
                    ref="drawdownChartRef"
                    class="portfolio-chart portfolio-chart--drawdown"
                  />
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane
              :label="t('portfolio.tabAllocation')"
              name="allocation"
            >
              <div
                v-if="activeTab === 'allocation'"
                class="portfolio-tab-panel"
              >
                <div class="portfolio-section-heading">
                  <h3>{{ t('portfolio.tabAllocation') }}</h3>
                  <span>{{ t('portfolio.allocationDesc') }}</span>
                </div>
                <div
                  v-if="isTabLoading('allocation')"
                  class="portfolio-querying"
                >
                  <el-icon
                    class="is-loading"
                    aria-hidden="true"
                  >
                    <Loading />
                  </el-icon>
                  <span>{{ t('portfolio.querying') }}</span>
                </div>
                <div
                  v-else-if="allocationItems.length === 0"
                  class="portfolio-empty"
                >
                  <el-icon aria-hidden="true">
                    <DataLine />
                  </el-icon>
                  <span>{{ t('portfolio.emptyAllocation') }}</span>
                </div>
                <div
                  v-else
                  ref="allocationChartRef"
                  class="portfolio-chart portfolio-chart--allocation"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </section>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick, onBeforeUnmount, computed, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Connection,
  DataLine,
  Histogram,
  Loading,
  Operation,
  Refresh,
  TrendCharts,
  Wallet,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type * as echarts from 'echarts'
import { getErrorMessage } from '@/api'
import { portfolioApi } from '@/api/portfolio'
import PortfolioAnalyticsTaskPanel from '@/components/portfolio/PortfolioAnalyticsTaskPanel.vue'
import type { PortfolioLedgerImportSource, PortfolioLedgerImportSourceDetail } from '@/api/portfolioLedger'
import { portfolioLedgerApi } from '@/api/portfolioLedger'
import { workspaceApi } from '@/api/workspace'
import type {
  PortfolioOverview,
  PositionItem,
  PositionSummary,
  TradeItem,
  PortfolioEquity,
  AllocationItem,
  PortfolioCompositionProjection,
  PortfolioCompositionSource,
  PortfolioCompositionVersionOption,
  PortfolioValuationInput,
} from '@/api/portfolio'
import type {
  TradingPositionManagerItem,
  Workspace,
} from '@/types/workspace'
import { PORTFOLIO_DRAWDOWN_AREA_COLOR, PORTFOLIO_DRAWDOWN_COLOR } from '@/constants/chartColors'

const { t } = useI18n()

const loading = ref(true)
const activeTab = ref('workspaces')
const viewMode = ref<'legacy' | 'composition'>('legacy')
const compositionVersions = ref<PortfolioCompositionVersionOption[]>([])
const selectedCompositionKey = ref('')
const compositionProjection = ref<PortfolioCompositionProjection | null>(null)
const compositionListLoading = ref(false)
const compositionProjectionLoading = ref(false)
const compositionError = ref('')
const compositionPage = ref(1)
const compositionHasMore = ref(false)
const compositionTotal = ref(0)
const compositionListChanged = ref(false)
const showImportedSourceDialog = ref(false)
const sourceImportBusy = ref(false)
const sourceImportError = ref('')
const importedSourceDetailError = ref('')
const existingImportsLoading = ref(false)
const existingImportSources = ref<PortfolioLedgerImportSource[]>([])
const existingImportSourcesPage = ref(1)
const existingImportSourcesHasMore = ref(false)
const selectedImportVersionId = ref('')
const importedSourceLoadingId = ref('')
const importedSourceDetails = ref<Record<string, PortfolioLedgerImportSourceDetail>>({})
const importPortfolioName = ref('')
const importPortfolioRef = ref('')
const importBaseCurrency = ref('')
const importSourceAsOf = ref('')
const importSourceCurrency = ref('')
const importTransactionsJson = ref('[]')
const pendingImportPortfolioId = ref('')
const pendingImportVersionId = ref('')
const importIdempotencyKey = ref('')
let compositionListRequestSequence = 0
let compositionProjectionRequestSequence = 0

const selectedCompositionVersion = computed(() => compositionVersions.value.find(
  version => compositionVersionKey(version) === selectedCompositionKey.value,
))
const selectedImportSource = computed(() => existingImportSources.value.find(
  source => source.import_version_id === selectedImportVersionId.value,
))

const overview = ref<PortfolioOverview>({
  total_assets: 0, total_cash: 0, total_position_value: 0, net_position_value: 0,
  total_initial_capital: 0, total_pnl: 0, total_pnl_pct: 0,
  strategy_count: 0, running_count: 0, strategies: [],
})
const positions = ref<PositionItem[]>([])
const trades = ref<TradeItem[]>([])
const equityData = ref<PortfolioEquity | null>(null)
const allocationItems = ref<AllocationItem[]>([])
const runningWorkspaces = ref<Workspace[]>([])
const tradingWorkspaces = ref<Workspace[]>([])
const positionSummary = ref<PositionSummary>(emptyPositionSummary())
const selectedEquitySeries = ref('portfolio')
const loadingTabs = ref<Set<string>>(new Set())
const POSITION_EPSILON = 1e-12

interface EquityCurveSelection {
  name: string
  dates: string[]
  values: number[]
  cumulativePnl: number[]
  drawdown: number[]
}

const selectedEquityCurve = computed<EquityCurveSelection>(() => {
  const data = equityData.value
  if (!data) return { name: '', dates: [], values: [], cumulativePnl: [], drawdown: [] }

  let name = t('portfolio.seriesTotalEquity')
  let sourceValues = data.total_equity
  let sourcePnlValues = data.cumulative_pnl ?? []
  let sourceDrawdownValues: number[] | undefined = data.total_drawdown
  if (selectedEquitySeries.value !== 'portfolio') {
    const strategy = data.strategies.find(item => item.instance_id === selectedEquitySeries.value)
    if (!strategy) return { name: '', dates: [], values: [], cumulativePnl: [], drawdown: [] }
    name = strategy.strategy_name
    sourceValues = strategy.values
    sourcePnlValues = strategy.pnl_values ?? []
    sourceDrawdownValues = undefined
  }

  const pointCount = Math.min(data.dates.length, sourceValues.length)
  const normalizedValues = sourceValues
    .slice(0, pointCount)
    .map(value => Number(value))
  const firstValueIndex = normalizedValues.findIndex(value => (
    Number.isFinite(value) && Math.abs(value) > POSITION_EPSILON
  ))
  if (firstValueIndex === -1) return { name, dates: [], values: [], cumulativePnl: [], drawdown: [] }

  const values = normalizedValues.slice(firstValueIndex)
  const dates = data.dates.slice(firstValueIndex, pointCount)
  const cumulativePnl = sourcePnlValues
    .slice(0, pointCount)
    .map(value => Number(value || 0))
    .slice(firstValueIndex)
  const suppliedDrawdown = sourceDrawdownValues
    ?.slice(0, pointCount)
    .map(value => Number(value))
  const drawdown = suppliedDrawdown?.length === pointCount
    && suppliedDrawdown.every(value => Number.isFinite(value))
    ? suppliedDrawdown.slice(firstValueIndex)
    : calculateDrawdown(values)
  return { name, dates, values, cumulativePnl, drawdown }
})

function calculateDrawdown(values: number[]) {
  let peak = values[0] ?? 0
  return values.map(value => {
    peak = Math.max(peak, value)
    return peak > 0 && value < peak ? -((peak - value) / peak) : 0
  })
}

function compositionVersionKey(version: PortfolioCompositionVersionOption) {
  return JSON.stringify([version.portfolio_ref, version.membership_version])
}

function compositionSourceLabel(source: PortfolioCompositionSource) {
  const keys: Record<PortfolioCompositionSource, string> = {
    research: 'portfolio.compositionSourceResearch',
    imported: 'portfolio.compositionSourceImported',
    paper: 'portfolio.compositionSourcePaper',
    live: 'portfolio.compositionSourceLive',
  }
  return t(keys[source])
}

function compositionStatusLabel(status: string) {
  if (status === 'adapter_not_integrated') return t('portfolio.compositionAdapterUnavailable')
  if (status === 'projected') return t('portfolio.compositionStatusProjected')
  if (status === 'no_account_members') return t('portfolio.compositionStatusNoAccounts')
  if (status === 'research_reports_projected') return t('portfolio.compositionResearchProjected')
  if (status === 'research_reports_unavailable') return t('portfolio.compositionResearchUnavailable')
  if (status === 'imported_materials_projected') return t('portfolio.importSourceProjected')
  if (status === 'imported_materials_unavailable') return t('portfolio.importSourceUnavailable')
  if (status === 'imported_material_integrity_invalid') return t('portfolio.importSourceIntegrityUnavailable')
  return status
}

function compositionAttributionStatusLabel(status: string) {
  if (status === 'not_applicable_research') return t('portfolio.compositionResearchNoAttribution')
  if (status === 'not_applicable_imported') return t('portfolio.importSourceNoAttribution')
  if (status === 'execution_attribution_not_collected') {
    return t('portfolio.compositionAttributionUnavailable')
  }
  return status
}

function compositionAmount(value: string | null, currency: string | null) {
  if (value === null) return t('portfolio.compositionUnavailable')
  return currency ? `${value} ${currency}` : value
}

function portfolioValuationInputText(input: PortfolioValuationInput) {
  const value = input.value === null
    ? input.status === 'missing' ? 'value missing' : ''
    : `value ${input.value}${input.currency ? ` ${input.currency}` : ''}${input.unit ? `/${input.unit}` : ''}`
  const provenance = input.provenance_ref || input.source?.provenance_ref
  const metadataVersion = input.metadata_version || input.source?.metadata_version
  const binding = input.binding_ref
    ? `${input.binding_ref}${input.binding_version ? `@${input.binding_version}` : ''}`
    : undefined
  const marketBinding = input.source?.binding_ref
    ? `${input.source.binding_ref}@${input.source.binding_version}`
    : undefined
  return [
    input.status,
    input.code || undefined,
    value || undefined,
    input.from_currency && input.to_currency
      ? `${input.from_currency}→${input.to_currency} ${input.rate_convention || ''}`
      : undefined,
    input.observed_at_utc ? `event ${input.observed_at_utc}` : undefined,
    input.age_seconds === undefined ? undefined : `age ${input.age_seconds}s`,
    binding ? `binding ${binding}` : undefined,
    marketBinding ? `market binding ${marketBinding}` : undefined,
    input.source?.canonical_id ? `identity ${input.source.canonical_id}` : undefined,
    input.source?.query_id ? `query ${input.source.query_id}` : undefined,
    input.source?.source_policy_id ? `policy ${input.source.source_policy_id}` : undefined,
    provenance ? `source ${provenance}` : undefined,
    metadataVersion ? `metadata ${metadataVersion}` : undefined,
    input.quantity_unit ? `quantity ${input.quantity_unit}` : undefined,
    input.position_quantity_unit ? `position quantity ${input.position_quantity_unit}` : undefined,
    input.valid_from_utc ? `valid from ${input.valid_from_utc}` : undefined,
    input.valid_to_utc ? `valid to ${input.valid_to_utc}` : undefined,
  ].filter(Boolean).join(' · ')
}

function compositionResearchArtifactStatusLabel(status: string) {
  if (status === 'available') return t('portfolio.compositionResearchArtifactAvailable')
  if (status === 'missing_or_not_owned') return t('portfolio.compositionResearchArtifactUnavailable')
  if (status === 'integrity_invalid') return t('portfolio.compositionResearchArtifactInvalid')
  return status
}

function compositionResearchIntegrityLabel(status: string) {
  if (status === 'verified') return t('portfolio.compositionResearchIntegrityVerified')
  if (status === 'invalid') return t('portfolio.compositionResearchArtifactInvalid')
  return t('portfolio.compositionResearchArtifactUnavailable')
}

function importSourceArtifactStatusLabel(status: string) {
  if (status === 'available' || status === 'verified') return t('portfolio.importSourceVerified')
  if (status === 'integrity_invalid') return t('portfolio.importSourceIntegrityUnavailable')
  if (status === 'source_material_unavailable' || status === 'unavailable_legacy') {
    return t('portfolio.importSourceLegacyUnavailable')
  }
  return t('portfolio.importSourceUnavailable')
}

function importSourceDateCoverageLabel(status: string) {
  const labels: Record<string, string> = {
    complete: 'portfolio.importSourceDateCoverageComplete',
    partial: 'portfolio.importSourceDateCoveragePartial',
    missing: 'portfolio.importSourceDateCoverageMissing',
    not_applicable_empty_source: 'portfolio.importSourceDateCoverageEmpty',
  }
  const key = labels[status]
  return key ? t(key) : t('portfolio.importSourceUnknown')
}

function newImportIdempotencyKey() {
  return `afi-import-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function openImportedSourceDialog() {
  showImportedSourceDialog.value = true
  sourceImportError.value = ''
  if (!importPortfolioName.value) importPortfolioName.value = t('portfolio.importSourceDefaultName')
  if (!importPortfolioRef.value) importPortfolioRef.value = `imported-${Date.now()}`
  if (!importIdempotencyKey.value) importIdempotencyKey.value = newImportIdempotencyKey()
  void loadExistingImportSources()
}

async function loadExistingImportSources(page = 1) {
  if (existingImportsLoading.value) return
  existingImportsLoading.value = true
  sourceImportError.value = ''
  try {
    const result = await portfolioLedgerApi.listImportSources(page, 100)
    if (page === 1) existingImportSources.value = result.items
    else existingImportSources.value = [...existingImportSources.value, ...result.items]
    existingImportSourcesPage.value = result.page
    existingImportSourcesHasMore.value = result.has_more
    if (
      !selectedImportVersionId.value
      || !existingImportSources.value.some(item => item.import_version_id === selectedImportVersionId.value)
    ) {
      selectedImportVersionId.value = result.items.find(
        item => item.source_material_status === 'verified',
      )?.import_version_id ?? ''
    }
  } catch (error: unknown) {
    sourceImportError.value = getErrorMessage(error, t('portfolio.importSourceLoadFailed'))
  } finally {
    existingImportsLoading.value = false
  }
}

async function loadMoreImportedSources() {
  if (!existingImportSourcesHasMore.value || existingImportsLoading.value) return
  const nextPage = existingImportSourcesPage.value + 1
  existingImportsLoading.value = true
  try {
    const result = await portfolioLedgerApi.listImportSources(nextPage, 100)
    if (result.total !== existingImportSources.value.length + result.items.length) {
      existingImportsLoading.value = false
      await loadExistingImportSources(1)
      return
    }
    existingImportSources.value = [...existingImportSources.value, ...result.items]
    existingImportSourcesPage.value = result.page
    existingImportSourcesHasMore.value = result.has_more
  } catch (error: unknown) {
    sourceImportError.value = getErrorMessage(error, t('portfolio.importSourceLoadFailed'))
  } finally {
    existingImportsLoading.value = false
  }
}

async function createImportedComposition(importVersionId: string, portfolioRef: string, baseCurrency: string) {
  const created = await portfolioApi.createCompositionVersion({
    portfolio_ref: portfolioRef,
    source_type: 'imported',
    base_currency: baseCurrency,
    members: [{ kind: 'imported_ledger', ref: importVersionId }],
  })
  selectedCompositionKey.value = JSON.stringify([created.portfolio_ref, created.membership_version])
  showImportedSourceDialog.value = false
  await loadCompositionData()
}

async function attachExistingImportSource() {
  const source = selectedImportSource.value
  if (!source || source.source_material_status !== 'verified' || sourceImportBusy.value) return
  sourceImportBusy.value = true
  sourceImportError.value = ''
  try {
    await createImportedComposition(
      source.import_version_id,
      `import-${source.import_version_id}`,
      source.base_currency,
    )
  } catch (error: unknown) {
    sourceImportError.value = getErrorMessage(error, t('portfolio.importSourceAttachFailed'))
  } finally {
    sourceImportBusy.value = false
  }
}

function parseImportTransactions(): Array<Record<string, unknown>> {
  let parsed: unknown
  try {
    parsed = JSON.parse(importTransactionsJson.value)
  } catch {
    throw new Error(t('portfolio.importSourceInvalidJson'))
  }
  if (
    !Array.isArray(parsed)
    || parsed.some(row => row === null || typeof row !== 'object' || Array.isArray(row))
  ) {
    throw new Error(t('portfolio.importSourceRowsInvalid'))
  }
  return parsed as Array<Record<string, unknown>>
}

async function importTransactionsAsComposition() {
  if (sourceImportBusy.value) return
  sourceImportError.value = ''
  sourceImportBusy.value = true
  try {
    const rows = parseImportTransactions()
    const baseCurrency = importBaseCurrency.value.trim()
    const portfolioName = importPortfolioName.value.trim()
    const portfolioRef = importPortfolioRef.value.trim()
    if (!portfolioName || !portfolioRef || !/^[A-Z0-9]{3,16}$/.test(baseCurrency)) {
      throw new Error(t('portfolio.importSourceFieldsInvalid'))
    }
    if (importSourceCurrency.value && !/^[A-Z0-9]{3,16}$/.test(importSourceCurrency.value)) {
      throw new Error(t('portfolio.importSourceCurrencyInvalid'))
    }
    if (!pendingImportPortfolioId.value) {
      const portfolio = await portfolioLedgerApi.create({
        name: portfolioName,
        base_currency: baseCurrency,
        source_type: 'imported',
      })
      pendingImportPortfolioId.value = portfolio.id
    }
    if (!pendingImportVersionId.value) {
      const imported = await portfolioLedgerApi.importTransactions(
        pendingImportPortfolioId.value,
        {
          format: 'json',
          idempotency_key: importIdempotencyKey.value,
          transactions: rows,
          source_as_of: importSourceAsOf.value || undefined,
          source_currency: importSourceCurrency.value || undefined,
        },
      )
      if (imported.source_material_status !== 'verified') {
        throw new Error(t('portfolio.importSourceIntegrityUnavailable'))
      }
      pendingImportVersionId.value = imported.import_version_id
    }
    await createImportedComposition(
      pendingImportVersionId.value,
      portfolioRef,
      baseCurrency,
    )
    importPortfolioName.value = ''
    importPortfolioRef.value = ''
    importBaseCurrency.value = ''
    importSourceAsOf.value = ''
    importSourceCurrency.value = ''
    importTransactionsJson.value = '[]'
    pendingImportPortfolioId.value = ''
    pendingImportVersionId.value = ''
    importIdempotencyKey.value = ''
  } catch (error: unknown) {
    sourceImportError.value = getErrorMessage(error, t('portfolio.importSourceCreateFailed'))
  } finally {
    sourceImportBusy.value = false
  }
}

async function loadImportedSourceDetail(importVersionId: string) {
  if (!importVersionId || importedSourceLoadingId.value) return
  if (importedSourceDetails.value[importVersionId]) return
  importedSourceLoadingId.value = importVersionId
  importedSourceDetailError.value = ''
  try {
    const detail = await portfolioLedgerApi.getImportSource(importVersionId)
    if (detail.source_material_status !== 'verified' || !detail.source_document) {
      importedSourceDetailError.value = t('portfolio.importSourceIntegrityUnavailable')
      return
    }
    importedSourceDetails.value = {
      ...importedSourceDetails.value,
      [importVersionId]: detail,
    }
  } catch (error: unknown) {
    importedSourceDetailError.value = getErrorMessage(error, t('portfolio.importSourceLoadFailed'))
  } finally {
    importedSourceLoadingId.value = ''
  }
}

function setViewMode(mode: 'legacy' | 'composition') {
  if (viewMode.value === mode) return
  viewMode.value = mode
  compositionListRequestSequence += 1
  compositionProjectionRequestSequence += 1
  if (mode === 'legacy') compositionProjection.value = null
  void loadData()
}

async function loadCompositionData(listChanged = false) {
  const requestSequence = ++compositionListRequestSequence
  const preferredKey = selectedCompositionKey.value
  compositionError.value = ''
  compositionListChanged.value = listChanged
  compositionProjection.value = null
  compositionListLoading.value = true
  try {
    const page = await portfolioApi.listCompositionVersions(1, 50)
    if (requestSequence !== compositionListRequestSequence || viewMode.value !== 'composition') return
    compositionVersions.value = page.items
    compositionPage.value = page.page
    compositionHasMore.value = page.has_more
    compositionTotal.value = page.total
    if (page.items.length === 0) {
      selectedCompositionKey.value = ''
      return
    }
    const preferred = page.items.find(version => compositionVersionKey(version) === preferredKey)
    const firstVersion = page.items[0]
    if (!firstVersion) {
      selectedCompositionKey.value = ''
      return
    }
    selectedCompositionKey.value = compositionVersionKey(preferred ?? firstVersion)
    await loadCompositionProjection()
  } catch (error: unknown) {
    if (requestSequence === compositionListRequestSequence) {
      compositionVersions.value = []
      selectedCompositionKey.value = ''
      compositionProjection.value = null
      compositionHasMore.value = false
      compositionTotal.value = 0
      compositionError.value = getErrorMessage(error, t('portfolio.compositionLoadFailed'))
    }
  } finally {
    if (requestSequence === compositionListRequestSequence) compositionListLoading.value = false
  }
}

async function loadCompositionProjection() {
  const requestSequence = ++compositionProjectionRequestSequence
  const selected = selectedCompositionVersion.value
  compositionError.value = ''
  compositionProjection.value = null
  if (!selected) {
    compositionProjectionLoading.value = false
    return
  }

  compositionProjectionLoading.value = true
  try {
    const projection = await portfolioApi.getCompositionProjection(
      selected.portfolio_ref,
      selected.membership_version,
    )
    if (requestSequence === compositionProjectionRequestSequence && viewMode.value === 'composition') {
      compositionProjection.value = projection
    }
  } catch (error: unknown) {
    if (requestSequence === compositionProjectionRequestSequence) {
      compositionProjection.value = null
      compositionError.value = getErrorMessage(error, t('portfolio.compositionLoadFailed'))
    }
  } finally {
    if (requestSequence === compositionProjectionRequestSequence) {
      compositionProjectionLoading.value = false
    }
  }
}

async function loadMoreCompositionVersions() {
  if (!compositionHasMore.value || compositionListLoading.value) return
  const requestSequence = ++compositionListRequestSequence
  const nextPage = compositionPage.value + 1
  compositionError.value = ''
  compositionListChanged.value = false
  compositionListLoading.value = true
  try {
    const page = await portfolioApi.listCompositionVersions(nextPage, 50)
    if (requestSequence !== compositionListRequestSequence || viewMode.value !== 'composition') return
    if (page.total !== compositionTotal.value) {
      await loadCompositionData(true)
      return
    }
    const versionsByKey = new Map(
      compositionVersions.value.map(version => [compositionVersionKey(version), version]),
    )
    for (const version of page.items) {
      const key = compositionVersionKey(version)
      if (!versionsByKey.has(key)) versionsByKey.set(key, version)
    }
    if (!page.has_more && versionsByKey.size !== page.total) {
      await loadCompositionData(true)
      return
    }
    compositionVersions.value = [...versionsByKey.values()]
    compositionPage.value = page.page
    compositionHasMore.value = page.has_more
    compositionTotal.value = page.total
  } catch (error: unknown) {
    if (requestSequence === compositionListRequestSequence) {
      compositionError.value = getErrorMessage(error, t('portfolio.compositionLoadFailed'))
    }
  } finally {
    if (requestSequence === compositionListRequestSequence) compositionListLoading.value = false
  }
}

// Chart refs
const pnlChartRef = ref<HTMLElement | null>(null)
const drawdownChartRef = ref<HTMLElement | null>(null)
const allocationChartRef = ref<HTMLElement | null>(null)
let pnlChart: echarts.ECharts | null = null
let drawdownChart: echarts.ECharts | null = null
let allocationChart: echarts.ECharts | null = null
let echartsLoader: Promise<typeof echarts> | null = null

function loadEcharts() {
  echartsLoader ??= import('echarts')
  return echartsLoader
}

function formatMoney(v: number) {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + t('portfolio.unitYi')
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + t('portfolio.unitWan')
  return v.toFixed(2)
}

function formatSignedMoney(v: number) {
  return `${v >= 0 ? '+' : ''}${formatMoney(v)}`
}

function formatSignedPercent(v: number) {
  const n = Number(v || 0)
  return `(${n >= 0 ? '+' : ''}${n.toFixed(2)}%)`
}

function formatNumber(v: number | null | undefined, digits = 2) {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : '--'
}

function formatOptionalMoney(v: number | null | undefined) {
  const n = Number(v)
  return Number.isFinite(n) ? formatMoney(n) : '--'
}

function formatPositionSize(v: number | null | undefined) {
  const n = Number(v || 0)
  if (!Number.isFinite(n) || n === 0) return '--'
  if (Math.abs(n) < 0.0001) return n.toFixed(8).replace(/\.?0+$/, '')
  return formatNumber(n, 4)
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '--'
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 19)
}

function signedValueClass(v: number | null | undefined) {
  const n = Number(v || 0)
  if (n > 0) return 'text-green-600'
  if (n < 0) return 'text-red-600'
  return 'text-gray-700'
}

function exposureValueClass(v: number | null | undefined) {
  const n = Number(v || 0)
  if (n > 0) return 'text-red-600'
  if (n < 0) return 'text-green-600'
  return 'text-gray-700'
}

function directionLabel(direction: string) {
  if (direction === 'long') return t('portfolio.directionLong')
  if (direction === 'short') return t('portfolio.directionShort')
  if (direction === 'hedged') return t('portfolio.directionHedged')
  return t('portfolio.directionFlat')
}

function positionDirectionTag(row: PositionItem) {
  if (row.direction === 'hedged') return 'warning'
  if (Number(row.size || 0) > 0) return 'danger'
  if (Number(row.size || 0) < 0) return 'success'
  return 'info'
}

function isLongTradeDirection(direction: string | null | undefined) {
  const normalized = String(direction || '').toLowerCase()
  return normalized === 'long' || normalized === 'buy'
}

function isShortTradeDirection(direction: string | null | undefined) {
  const normalized = String(direction || '').toLowerCase()
  return normalized === 'short' || normalized === 'sell'
}

function tradeDirectionLabel(direction: string | null | undefined) {
  if (isLongTradeDirection(direction)) return t('portfolio.directionLong')
  if (isShortTradeDirection(direction)) return t('portfolio.directionShort')
  return String(direction || '--')
}

function tradeDirectionClass(direction: string | null | undefined) {
  if (isLongTradeDirection(direction)) return 'text-red-600'
  if (isShortTradeDirection(direction)) return 'text-green-600'
  return 'text-gray-700'
}

function emptyPositionSummary(): PositionSummary {
  return {
    total_long_value: 0,
    total_short_value: 0,
    gross_market_value: 0,
    net_market_value: 0,
    total_pnl: 0,
    long_count: 0,
    short_count: 0,
    flat_count: 0,
  }
}

const loadedTabs = ref<Set<string>>(new Set(['workspaces']))
const portfolioWorkspaces = computed(() => runningWorkspaces.value)
const portfolioWorkspaceIds = computed(() => portfolioWorkspaces.value.map(workspace => workspace.id))
const selectedPositionValue = computed(() => (
  positionSummary.value.gross_market_value
))
type MetricTone = 'primary' | 'success' | 'warning' | 'danger' | 'neutral'

interface PortfolioMetricCard {
  label: string
  value: string
  helper: string
  icon: Component
  tone: MetricTone
  valueClass?: string
}

const portfolioHealthLabel = computed(() => {
  if (overview.value.total_pnl > 0) return t('portfolio.riskPosturePositive')
  if (overview.value.total_pnl < 0) return t('portfolio.riskPostureNegative')
  return t('portfolio.riskPostureNeutral')
})

const heroBadges = computed(() => [
  { label: t('portfolio.heroCash'), value: formatMoney(overview.value.total_cash) },
  { label: t('portfolio.heroStrategies'), value: String(overview.value.strategy_count) },
  { label: t('portfolio.heroWorkspaces'), value: String(runningWorkspaces.value.length) },
])

const summaryCards = computed<PortfolioMetricCard[]>(() => [
  {
    label: t('portfolio.cardTotalAssets'),
    value: formatMoney(overview.value.total_assets),
    helper: t('portfolio.cardTotalAssetsHelper'),
    icon: Wallet,
    tone: 'primary',
  },
  {
    label: t('portfolio.cardTotalPnl'),
    value: `${formatSignedMoney(overview.value.total_pnl)} ${formatSignedPercent(overview.value.total_pnl_pct)}`,
    helper: t('portfolio.cardTotalPnlHelper'),
    icon: TrendCharts,
    tone: overview.value.total_pnl >= 0 ? 'success' : 'danger',
    valueClass: signedValueClass(overview.value.total_pnl),
  },
  {
    label: t('portfolio.cardPositionValue'),
    value: formatMoney(selectedPositionValue.value || overview.value.total_position_value),
    helper: t('portfolio.cardPositionValueHelper'),
    icon: Histogram,
    tone: 'warning',
  },
  {
    label: t('portfolio.cardWorkspaceRunning'),
    value: String(runningWorkspaces.value.length),
    helper: t('portfolio.cardWorkspaceRunningHelper'),
    icon: Connection,
    tone: 'neutral',
  },
])

const positionMetricCards = computed(() => [
  {
    label: t('portfolio.cardLongValue'),
    value: formatMoney(positionSummary.value.total_long_value),
    valueClass: 'text-red-600',
  },
  {
    label: t('portfolio.cardShortValue'),
    value: formatMoney(positionSummary.value.total_short_value),
    valueClass: 'text-green-600',
  },
  {
    label: t('portfolio.cardNetExposure'),
    value: formatSignedMoney(positionSummary.value.net_market_value),
    valueClass: exposureValueClass(positionSummary.value.net_market_value),
  },
  {
    label: t('portfolio.cardPositionPnl'),
    value: formatSignedMoney(positionSummary.value.total_pnl),
    valueClass: signedValueClass(positionSummary.value.total_pnl),
  },
])

function workspaceStatusLabel(status: string) {
  const map: Record<string, string> = {
    running: t('portfolio.statusRunning'),
    error: t('portfolio.statusError'),
    idle: t('portfolio.statusStopped'),
    completed: t('portfolio.statusStopped'),
  }
  return map[status] || status
}

function valuationStatusTag(row: PositionItem) {
  const status = String(row.valuation_status || '').toLowerCase()
  if (row.position_source === 'gateway' && status === 'confirmed') return 'success'
  if (status === 'stale_fallback') return 'danger'
  if (status === 'estimated' || (row.valuation_warnings?.length ?? 0) > 0) return 'warning'
  return 'info'
}

function valuationStatusLabel(row: PositionItem) {
  const status = String(row.valuation_status || '').toLowerCase()
  if (row.position_source === 'gateway' && status === 'confirmed') return t('portfolio.valuationGatewayConfirmed')
  if (status === 'stale_fallback') return t('portfolio.valuationStale')
  if (status === 'estimated' || (row.valuation_warnings?.length ?? 0) > 0) return t('portfolio.valuationEstimated')
  return t('portfolio.valuationUnknown')
}

function positionSourceLabel(value: string | null | undefined) {
  const source = String(value || '').toLowerCase()
  if (source === 'gateway') return t('portfolio.sourceGateway')
  if (source === 'log') return t('portfolio.sourceLog')
  if (source === 'snapshot') return t('portfolio.sourceSnapshot')
  if (source === 'mixed') return t('portfolio.sourceMixed')
  return t('portfolio.sourceUnknown')
}

function valuationTooltip(row: PositionItem) {
  const warnings = row.valuation_warnings?.filter(Boolean) ?? []
  if (warnings.length > 0) return warnings.join('；')
  const assetSource = row.asset_spec_source || '--'
  return `${t('portfolio.positionSource')}: ${positionSourceLabel(row.position_source)}；${t('portfolio.assetSpecSource')}: ${assetSource}`
}

async function loadData() {
  loading.value = true
  loadedTabs.value = new Set(['workspaces'])
  loadingTabs.value = new Set()
  try {
    if (viewMode.value === 'composition') {
      await loadCompositionData()
      return
    }
    const [dashboard, workspaceList] = await Promise.all([
      portfolioApi.getOverview(true),
      workspaceApi.list(0, 100, 'trading'),
    ])
    overview.value = dashboard
    tradingWorkspaces.value = workspaceList.items
    runningWorkspaces.value = tradingWorkspaces.value.filter(workspace => workspace.status === 'running')
    if (activeTab.value !== 'workspaces') {
      await loadTabData(activeTab.value)
    }
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, t('portfolio.msgLoadFailed')))
  } finally {
    loading.value = false
  }
}

function isTabLoading(tab: string) {
  return loadingTabs.value.has(tab)
}

function setTabLoading(tab: string, isLoading: boolean) {
  const next = new Set(loadingTabs.value)
  if (isLoading) next.add(tab)
  else next.delete(tab)
  loadingTabs.value = next
}

async function loadTabData(tab: string) {
  if (loadedTabs.value.has(tab) || isTabLoading(tab)) return
  setTabLoading(tab, true)
  try {
    if (tab === 'positions') {
      await loadWorkspacePositions()
    } else if (tab === 'trades') {
      await loadWorkspaceTrades()
    } else if (tab === 'equity') {
      equityData.value = await portfolioApi.getEquity(portfolioWorkspaceIds.value, false)
      selectedEquitySeries.value = 'portfolio'
    } else if (tab === 'allocation') {
      allocationItems.value = (await portfolioApi.getAllocation(portfolioWorkspaceIds.value)).items
    }
    loadedTabs.value = new Set([...loadedTabs.value, tab])
  } catch (e: unknown) {
    ElMessage.error(getErrorMessage(e, t('portfolio.msgLoadTabFailed')))
  } finally {
    setTabLoading(tab, false)
  }
}

async function loadWorkspacePositions() {
  const workspaces = portfolioWorkspaces.value
  if (workspaces.length === 0) {
    positions.value = []
    positionSummary.value = emptyPositionSummary()
    return
  }

  const positionResults = await Promise.all(
    workspaces.map(workspace => workspaceApi.getTradingPositions(workspace.id)),
  )

  const nextPositions = positionResults.flatMap((result, index) => (
    result.positions.map(item => mapWorkspacePosition(workspaces[index], item))
  )).filter(item => hasOpenPosition(item))
  positions.value = nextPositions
  positionSummary.value = buildWorkspacePositionSummary(nextPositions)
}

async function loadWorkspaceTrades() {
  const workspaces = portfolioWorkspaces.value
  if (workspaces.length === 0) {
    trades.value = []
    return
  }

  const result = await portfolioApi.getTrades(1000, portfolioWorkspaceIds.value, false)
  trades.value = result.trades
    .filter(item => isTradeInSelectedWorkspaces(item, workspaces))
    .sort((a, b) => tradeSortKey(b).localeCompare(tradeSortKey(a)))
}

function buildWorkspacePositionSummary(rows: PositionItem[]): PositionSummary {
  const exposure = rows.reduce((sum, item) => {
    const longMarketValue = Number(item.long_market_value)
    const shortMarketValue = Number(item.short_market_value)
    if (Number.isFinite(longMarketValue) || Number.isFinite(shortMarketValue)) {
      sum.long += Number.isFinite(longMarketValue) ? Math.max(longMarketValue, 0) : 0
      sum.short += Number.isFinite(shortMarketValue) ? Math.max(shortMarketValue, 0) : 0
      sum.pnl += Number(item.position_pnl || 0)
      return sum
    }
    const longPosition = Math.max(Number(item.long_position || 0), 0)
    const shortPosition = Math.max(Number(item.short_position || 0), 0)
    const marketValue = Math.abs(Number(item.market_value || 0))
    const totalPosition = longPosition + shortPosition
    if (totalPosition > 0) {
      sum.long += marketValue * (longPosition / totalPosition)
      sum.short += marketValue * (shortPosition / totalPosition)
    } else if (Number(item.size || 0) > 0) {
      sum.long += marketValue
    } else if (Number(item.size || 0) < 0) {
      sum.short += marketValue
    }
    sum.pnl += Number(item.position_pnl || 0)
    return sum
  }, { long: 0, short: 0, pnl: 0 })
  const totalLong = exposure.long
  const totalShort = exposure.short
  const totalPnl = exposure.pnl
  return {
    total_long_value: roundMoney(totalLong),
    total_short_value: roundMoney(totalShort),
    gross_market_value: roundMoney(totalLong + totalShort),
    net_market_value: roundMoney(totalLong - totalShort),
    total_pnl: roundMoney(totalPnl),
    long_count: rows.filter(item => Number(item.long_position || 0) > POSITION_EPSILON || Number(item.size || 0) > POSITION_EPSILON).length,
    short_count: rows.filter(item => Number(item.short_position || 0) > POSITION_EPSILON || Number(item.size || 0) < -POSITION_EPSILON).length,
    flat_count: rows.filter(item => !hasOpenPosition(item)).length,
  }
}

function roundMoney(v: number) {
  return Math.round((Number(v) || 0) * 100) / 100
}

function mapWorkspacePosition(
  workspace: Workspace,
  item: TradingPositionManagerItem,
): PositionItem {
  const longPosition = Number(item.long_position || 0)
  const shortPosition = Number(item.short_position || 0)
  const netSize = longPosition - shortPosition
  const latestPrice = Number(item.latest_price ?? item.avg_price ?? 0)
  const avgPrice = Number(item.avg_price ?? latestPrice)
  const direction = longPosition > 0 && shortPosition > 0
    ? 'hedged'
    : netSize > 0 ? 'long' : netSize < 0 ? 'short' : 'flat'
  return {
    strategy_id: item.unit_id,
    strategy_name: `${workspace.name} / ${item.unit_name}`,
    instance_id: item.unit_id,
    data_name: item.symbol,
    size: netSize,
    price: avgPrice,
    latest_price: latestPrice,
    market_value: Number(item.market_value ?? 0),
    margin_value: item.margin_value == null ? undefined : Number(item.margin_value),
    long_market_value: item.long_market_value == null ? undefined : Number(item.long_market_value),
    short_market_value: item.short_market_value == null ? undefined : Number(item.short_market_value),
    position_pnl: Number(item.position_pnl || 0),
    gross_pnl: item.gross_pnl == null ? undefined : Number(item.gross_pnl),
    commission: item.commission == null ? undefined : Number(item.commission),
    commission_source: item.commission_source,
    multiplier: item.multiplier == null ? undefined : Number(item.multiplier),
    margin_rate: item.margin_rate == null ? undefined : Number(item.margin_rate),
    leverage: item.leverage == null ? undefined : Number(item.leverage),
    direction,
    long_position: longPosition,
    short_position: shortPosition,
    trading_mode: item.trading_mode,
    updated_at: item.updated_at ?? workspace.updated_at,
    data_time: item.data_time,
    position_source: item.position_source,
    asset_spec_source: item.asset_spec_source,
    valuation_status: item.valuation_status,
    valuation_warnings: item.valuation_warnings ?? [],
  }
}

function hasOpenPosition(item: PositionItem) {
  return (
    Math.abs(Number(item.size || 0)) > POSITION_EPSILON
    || Number(item.long_position || 0) > POSITION_EPSILON
    || Number(item.short_position || 0) > POSITION_EPSILON
  )
}

function isTradeInSelectedWorkspaces(item: TradeItem, workspaces: Workspace[]) {
  if (item.workspace_id) {
    return workspaces.some(workspace => workspace.id === item.workspace_id)
  }
  const strategyName = String(item.strategy_name || '')
  return workspaces.some(workspace => (
    strategyName === workspace.name || strategyName.startsWith(`${workspace.name} /`)
  ))
}

function tradeSortKey(item: TradeItem) {
  return String(item.dtclose || item.datetime || item.dtopen || '')
}

function readThemeColor(name: string, fallback = 'currentColor') {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

function chartThemeColors() {
  return {
    text: readThemeColor('--text-color-secondary'),
    primaryText: readThemeColor('--text-color-primary'),
    border: readThemeColor('--border-color-light'),
    surface: readThemeColor('--bg-color'),
  }
}

// ---- Charts ----

async function renderPnlChart() {
  const curve = selectedEquityCurve.value
  if (!pnlChartRef.value || curve.values.length === 0) return
  const echarts = await loadEcharts()
  if (pnlChart && pnlChart.getDom() !== pnlChartRef.value) {
    pnlChart.dispose()
    pnlChart = null
  }
  if (!pnlChart) pnlChart = echarts.init(pnlChartRef.value)

  const colors = chartThemeColors()
  const latestPnl = curve.cumulativePnl[curve.cumulativePnl.length - 1] ?? 0
  const pnlColor = latestPnl >= 0
    ? readThemeColor('--success-color', '#238636')
    : readThemeColor('--danger-color', '#cf222e')
  pnlChart.setOption({
    title: {
      text: '累计 P&L',
      left: 80,
      top: 8,
      textStyle: { color: colors.primaryText, fontSize: 13, fontWeight: 600 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: colors.surface,
      borderColor: colors.border,
      textStyle: { color: colors.primaryText },
      formatter: (params: { axisValue?: string; value?: number } | { axisValue?: string; value?: number }[]) => {
        const p = Array.isArray(params) ? params[0] : params
        return `${p?.axisValue ?? ''}<br/>累计 P&L: ${formatSignedMoney(Number(p?.value ?? 0))}`
      },
    },
    grid: { left: 80, right: 20, top: 38, bottom: 30 },
    xAxis: {
      type: 'category',
      data: curve.dates,
      boundaryGap: false,
      show: false,
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: colors.text, formatter: (v: number) => formatMoney(v) },
      axisLine: { lineStyle: { color: colors.border } },
      splitLine: { lineStyle: { color: colors.border } },
    },
    series: [{
      name: '累计 P&L',
      type: 'line',
      data: curve.cumulativePnl,
      areaStyle: { color: pnlColor, opacity: 0.1 },
      lineStyle: { color: pnlColor, width: 1.5 },
      itemStyle: { color: pnlColor },
      symbol: 'none',
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: colors.text, type: 'dashed', opacity: 0.5 },
        label: { show: false },
        data: [{ yAxis: 0 }],
      },
    }],
  }, true)
  pnlChart.resize()
}

async function renderDrawdownChart() {
  const curve = selectedEquityCurve.value
  if (!drawdownChartRef.value || curve.values.length === 0) return
  const echarts = await loadEcharts()
  if (drawdownChart && drawdownChart.getDom() !== drawdownChartRef.value) {
    drawdownChart.dispose()
    drawdownChart = null
  }
  if (!drawdownChart) drawdownChart = echarts.init(drawdownChartRef.value)

  const colors = chartThemeColors()
  drawdownChart.setOption({
    title: {
      text: '回撤',
      left: 80,
      top: 8,
      textStyle: { color: colors.primaryText, fontSize: 13, fontWeight: 600 },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: colors.surface,
      borderColor: colors.border,
      textStyle: { color: colors.primaryText },
      formatter: (params: { axisValue?: string; value?: number } | { axisValue?: string; value?: number }[]) => {
        const p = Array.isArray(params) ? params[0] : params
        return `${p?.axisValue ?? ''}<br/>${t('portfolio.drawdownTooltip', { value: ((p?.value ?? 0) * 100).toFixed(2) })}`
      },
    },
    grid: { left: 80, right: 20, top: 38, bottom: 30 },
    xAxis: {
      type: 'category',
      data: curve.dates,
      boundaryGap: false,
      axisLabel: { color: colors.text },
      axisLine: { lineStyle: { color: colors.border } },
      axisTick: { lineStyle: { color: colors.border } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: colors.text, formatter: (v: number) => `${(v * 100).toFixed(1)}%` },
      axisLine: { lineStyle: { color: colors.border } },
      splitLine: { lineStyle: { color: colors.border } },
    },
    series: [{
      name: '回撤',
      type: 'line',
      data: curve.drawdown,
      areaStyle: { color: PORTFOLIO_DRAWDOWN_AREA_COLOR },
      lineStyle: { color: PORTFOLIO_DRAWDOWN_COLOR, width: 1 },
      itemStyle: { color: PORTFOLIO_DRAWDOWN_COLOR },
      symbol: 'none',
    }],
  }, true)
  drawdownChart.resize()
}

async function renderAllocationChart() {
  if (!allocationChartRef.value || allocationItems.value.length === 0) return
  const echarts = await loadEcharts()
  if (allocationChart && allocationChart.getDom() !== allocationChartRef.value) {
    allocationChart.dispose()
    allocationChart = null
  }
  if (!allocationChart) allocationChart = echarts.init(allocationChartRef.value)
  const colors = chartThemeColors()

  const pieData = allocationItems.value.map(item => ({
    name: item.asset,
    value: item.value,
  }))

  allocationChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} ({d}%)',
      backgroundColor: colors.surface,
      borderColor: colors.border,
      textStyle: { color: colors.primaryText },
    },
    legend: {
      orient: 'vertical',
      right: 20,
      top: 'center',
      type: 'scroll',
      textStyle: { color: colors.text },
    },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['40%', '50%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 6, borderColor: colors.surface, borderWidth: 2 },
      label: { show: true, color: colors.text, formatter: '{b}\n{d}%' },
      data: pieData,
    }],
  }, true)
  allocationChart.resize()
}

function handleResize() {
  pnlChart?.resize()
  drawdownChart?.resize()
  allocationChart?.resize()
}

watch(activeTab, async (tab) => {
  await loadTabData(tab)
  if (tab === 'equity') {
    nextTick(() => {
      void renderPnlChart()
      void renderDrawdownChart()
    })
  } else if (tab === 'allocation') {
    nextTick(() => { void renderAllocationChart() })
  }
})

watch(selectedEquitySeries, () => {
  if (activeTab.value !== 'equity') return
  nextTick(() => {
    void renderPnlChart()
    void renderDrawdownChart()
  })
})

onMounted(() => {
  loadData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  pnlChart?.dispose()
  drawdownChart?.dispose()
  allocationChart?.dispose()
})
</script>

<style scoped>
.portfolio-page {
  display: grid;
  gap: 20px;
  color: var(--text-color-primary);
}

.portfolio-view-switch {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.portfolio-view-switch button,
.portfolio-composition__refresh,
.portfolio-composition__selector button {
  min-height: 36px;
  padding: 7px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-color);
  color: var(--text-color-primary);
  cursor: pointer;
}

.portfolio-composition__refresh:disabled,
.portfolio-composition__selector button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.portfolio-view-switch button[aria-pressed='true'] {
  border-color: var(--primary-color);
  color: var(--primary-color);
  font-weight: 700;
}

.portfolio-composition {
  display: grid;
  gap: 20px;
  padding: 22px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-color);
}

.portfolio-composition__header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.portfolio-composition__header h1,
.portfolio-composition__section h2 {
  margin: 6px 0;
  color: var(--text-color-primary);
}

.portfolio-composition__header p,
.portfolio-composition__section p,
.portfolio-composition__status {
  color: var(--text-color-secondary);
  line-height: 1.6;
}

.portfolio-composition__selector {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.portfolio-composition__selector label {
  font-weight: 650;
}

.portfolio-composition__selector select {
  min-width: min(360px, 100%);
  min-height: 38px;
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-color);
  color: var(--text-color-primary);
}

.portfolio-composition__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin: 0;
}

.portfolio-composition__facts > div,
.portfolio-composition__section {
  padding: 14px;
  border: 1px solid var(--border-color-light);
  border-radius: 6px;
}

.portfolio-composition__facts dt {
  margin-bottom: 6px;
  color: var(--text-color-secondary);
  font-size: 13px;
}

.portfolio-composition__facts dd {
  margin: 0;
  overflow-wrap: anywhere;
  font-weight: 700;
}

.portfolio-composition__facts code,
.portfolio-composition__section li span {
  display: block;
  margin-top: 4px;
  color: var(--text-color-secondary);
  font-size: 12px;
  font-weight: 400;
}

.portfolio-composition__section ul {
  display: grid;
  gap: 8px;
  padding-left: 20px;
  overflow-wrap: anywhere;
}

.portfolio-import-source-dialog {
  background: var(--fill-color-lighter);
}

.portfolio-import-source-dialog__existing,
.portfolio-import-source-form {
  display: grid;
  gap: 12px;
}

.portfolio-import-source-dialog__existing {
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: end;
}

.portfolio-import-source-dialog__existing label,
.portfolio-import-source-form label {
  display: grid;
  gap: 5px;
  color: var(--text-color-secondary);
  font-size: 13px;
  font-weight: 650;
}

.portfolio-import-source-dialog__existing select,
.portfolio-import-source-form input,
.portfolio-import-source-form textarea {
  width: 100%;
  min-height: 36px;
  padding: 7px 9px;
  border: 1px solid var(--border-color);
  border-radius: 5px;
  background: var(--bg-color);
  color: var(--text-color-primary);
  font: inherit;
}

.portfolio-import-source-form fieldset {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin: 0;
  padding: 0;
  border: 0;
}

.portfolio-import-source-form fieldset:disabled {
  opacity: 0.65;
}

.portfolio-import-source-form__rows {
  grid-column: 1 / -1;
}

.portfolio-import-source-form textarea {
  min-height: 160px;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.portfolio-import-source-form__hint {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.portfolio-import-source-raw {
  max-height: 420px;
  overflow: auto;
  padding: 12px;
  border-radius: 5px;
  background: var(--fill-color-lighter);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.portfolio-composition__unavailable,
.portfolio-composition__error {
  padding: 12px 14px;
  border-radius: 6px;
  line-height: 1.6;
}

.portfolio-composition__unavailable {
  background: color-mix(in srgb, var(--warning-color, #d97706) 10%, var(--bg-color));
}

.portfolio-composition__error {
  color: var(--danger-color, #b91c1c);
  background: color-mix(in srgb, var(--danger-color, #b91c1c) 8%, var(--bg-color));
}

.portfolio-loading {
  display: grid;
  justify-items: center;
  gap: 12px;
  padding: 72px 16px;
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  background: var(--bg-color);
  color: var(--text-color-secondary);
}

.portfolio-loading__icon {
  color: var(--primary-color);
  font-size: 34px;
}

.portfolio-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
  gap: 18px;
  align-items: stretch;
  padding: 22px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--bg-color) 90%, var(--primary-color) 10%), transparent),
    var(--bg-color);
}

.portfolio-hero__copy {
  display: grid;
  align-content: center;
  gap: 12px;
  min-width: 0;
}

.portfolio-kicker {
  color: var(--primary-color);
  font-size: 12px;
  font-weight: 760;
  letter-spacing: 0;
  text-transform: uppercase;
}

.portfolio-hero h1,
.portfolio-panel-heading h2,
.portfolio-section-heading h3 {
  margin: 0;
  color: var(--text-color-primary);
  line-height: 1.2;
}

.portfolio-hero h1 {
  max-width: 780px;
  font-size: 40px;
  font-weight: 800;
}

.portfolio-hero p,
.portfolio-panel-heading p,
.portfolio-section-heading span {
  margin: 0;
  color: var(--text-color-secondary);
  line-height: 1.6;
}

.portfolio-hero p {
  max-width: 760px;
  font-size: 14px;
}

.portfolio-hero__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.portfolio-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 7px 10px;
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-color) 82%, var(--fill-color-light) 18%);
  color: var(--text-color-secondary);
  font-size: 12px;
}

.portfolio-badge strong {
  color: var(--text-color-primary);
  font-weight: 760;
}

.portfolio-hero__status {
  display: grid;
  align-content: space-between;
  gap: 14px;
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-color) 84%, var(--fill-color-light) 16%);
}

.portfolio-status-chip {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  gap: 8px;
  min-height: 30px;
  padding: 6px 10px;
  border: 1px solid var(--success-border-color);
  border-radius: 999px;
  background: color-mix(in srgb, var(--bg-color) 82%, var(--success-color) 18%);
  color: var(--success-color);
  font-size: 12px;
  font-weight: 700;
}

.portfolio-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentcolor;
}

.portfolio-hero__asset,
.portfolio-hero__pnl {
  display: grid;
  gap: 4px;
}

.portfolio-hero__asset span,
.portfolio-hero__pnl span {
  color: var(--text-color-secondary);
  font-size: 12px;
  font-weight: 650;
}

.portfolio-hero__asset strong,
.portfolio-hero__pnl {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 34px;
  font-weight: 820;
  line-height: 1.1;
}

.portfolio-refresh {
  justify-self: start;
  --el-button-bg-color: var(--fill-color-lighter);
  --el-button-border-color: var(--border-color);
  --el-button-text-color: var(--text-color-primary);
  --el-button-hover-bg-color: var(--fill-color-light);
  --el-button-hover-border-color: var(--info-border-color);
  --el-button-hover-text-color: var(--primary-color);
}

.portfolio-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.portfolio-metric,
.portfolio-workbench,
.portfolio-tab-panel {
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  background: var(--bg-color);
}

.portfolio-metric {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 8px 10px;
  align-items: start;
  min-width: 0;
  padding: 16px;
  overflow: hidden;
}

.portfolio-metric::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: var(--primary-color);
  content: "";
}

.portfolio-metric--success::before {
  background: var(--success-color);
}

.portfolio-metric--danger::before {
  background: var(--danger-color);
}

.portfolio-metric--warning::before {
  background: var(--warning-color);
}

.portfolio-metric--neutral::before {
  background: var(--text-color-placeholder);
}

.portfolio-metric__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  background: var(--fill-color-lighter);
  color: var(--primary-color);
  grid-row: span 3;
}

.portfolio-metric__label {
  min-width: 0;
  color: var(--text-color-secondary);
  font-size: 12px;
  font-weight: 700;
}

.portfolio-metric strong {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text-color-primary);
  font-size: 22px;
  font-weight: 820;
  line-height: 1.15;
}

.portfolio-metric small {
  min-width: 0;
  color: var(--text-color-secondary);
  font-size: 12px;
  line-height: 1.35;
}

.portfolio-layout {
  min-width: 0;
}

.portfolio-workbench {
  min-width: 0;
  padding: 16px;
}

.portfolio-panel-heading {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.portfolio-panel-heading--inline {
  margin-bottom: 14px;
}

.portfolio-panel-heading h2 {
  font-size: 18px;
  font-weight: 780;
}

.portfolio-panel-heading p {
  font-size: 13px;
}

.portfolio-workbench {
  overflow: hidden;
}

.portfolio-tabs {
  min-width: 0;
}

.portfolio-tabs :deep(.el-tabs__header) {
  margin: 0 0 12px;
}

.portfolio-tabs :deep(.el-tabs__nav-wrap::after) {
  background: var(--border-color-light);
}

.portfolio-tabs :deep(.el-tabs__item) {
  color: var(--text-color-secondary);
  font-weight: 700;
}

.portfolio-tabs :deep(.el-tabs__item.is-active),
.portfolio-tabs :deep(.el-tabs__active-bar) {
  color: var(--primary-color);
}

.portfolio-tab-panel {
  display: grid;
  gap: 14px;
  padding: 14px;
}

.portfolio-section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
  flex-wrap: wrap;
}

.portfolio-section-heading h3 {
  font-size: 16px;
  font-weight: 780;
}

.portfolio-section-heading span {
  max-width: 560px;
  font-size: 12px;
}

.portfolio-section-heading--chart > div {
  display: grid;
  gap: 4px;
}

.portfolio-equity-selector {
  width: min(100%, 260px);
}

.portfolio-exposure-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.portfolio-exposure-card {
  display: grid;
  gap: 5px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  background: var(--fill-color-lighter);
}

.portfolio-exposure-card span {
  color: var(--text-color-secondary);
  font-size: 12px;
  font-weight: 680;
}

.portfolio-exposure-card strong {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 18px;
  font-weight: 800;
  line-height: 1.15;
}

.portfolio-empty {
  display: grid;
  justify-items: center;
  gap: 10px;
  min-height: 180px;
  padding: 28px 16px;
  border: 1px dashed var(--border-color);
  border-radius: 8px;
  background: var(--fill-color-lighter);
  color: var(--text-color-secondary);
  text-align: center;
}

.portfolio-empty--compact {
  min-height: 120px;
}

.portfolio-querying {
  display: grid;
  justify-items: center;
  gap: 10px;
  min-height: 180px;
  padding: 28px 16px;
  border: 1px dashed var(--border-color);
  border-radius: 8px;
  background: var(--fill-color-lighter);
  color: var(--text-color-secondary);
  text-align: center;
}

.portfolio-querying .el-icon {
  color: var(--primary-color);
  font-size: 28px;
}

.portfolio-empty .el-icon {
  color: var(--primary-color);
  font-size: 28px;
}

.portfolio-table {
  width: 100%;
  overflow: hidden;
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  --el-table-bg-color: var(--bg-color);
  --el-table-tr-bg-color: var(--bg-color);
  --el-table-header-bg-color: var(--fill-color-lighter);
  --el-table-row-hover-bg-color: var(--fill-color-light);
  --el-table-border-color: var(--border-color-light);
  --el-table-text-color: var(--text-color-regular);
  --el-table-header-text-color: var(--text-color-secondary);
}

.portfolio-table :deep(.el-table__empty-block) {
  background: var(--bg-color);
}

.portfolio-chart-stack {
  display: grid;
  gap: 10px;
}

.portfolio-chart {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--border-color-light);
  border-radius: 8px;
  background: var(--fill-color-lighter);
}

.portfolio-chart--equity {
  height: 400px;
}

.portfolio-chart--pnl,
.portfolio-chart--drawdown {
  height: 180px;
}

.portfolio-chart--allocation {
  height: 430px;
}

.text-green-600 {
  color: var(--success-color);
  font-weight: 760;
}

.text-red-600 {
  color: var(--danger-color);
  font-weight: 760;
}

.text-gray-700 {
  color: var(--text-color-primary);
  font-weight: 760;
}

@media (max-width: 1180px) {
  .portfolio-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 980px) {
  .portfolio-hero {
    grid-template-columns: 1fr;
  }

  .portfolio-hero h1 {
    font-size: 34px;
  }
}

@media (max-width: 760px) {
  .portfolio-page {
    gap: 14px;
  }

  .portfolio-hero {
    grid-template-columns: 1fr;
    padding: 16px;
  }

  .portfolio-hero h1 {
    font-size: 28px;
  }

  .portfolio-hero__asset strong,
  .portfolio-hero__pnl {
    font-size: 28px;
  }

  .portfolio-overview,
  .portfolio-exposure-grid {
    grid-template-columns: 1fr;
  }

  .portfolio-workbench,
  .portfolio-tab-panel {
    padding: 12px;
  }

  .portfolio-section-heading {
    align-items: flex-start;
  }

  .portfolio-chart--equity {
    height: 320px;
  }

  .portfolio-chart--pnl,
  .portfolio-chart--drawdown {
    height: 160px;
  }

  .portfolio-chart--allocation {
    height: 340px;
  }
}
</style>
