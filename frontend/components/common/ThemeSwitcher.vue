<template>
  <div class="theme-switcher">
    <select v-model="selectedTheme" @change="onThemeChange" class="theme-select">
      <option v-for="t in availableThemes" :key="t.id" :value="t.id">
        {{ t.name }}
      </option>
    </select>
  </div>
</template>

<script setup lang="ts">
const { theme, setTheme, availableThemes } = useTheme()

const selectedTheme = ref(theme.value)

watch(theme, (value) => {
  selectedTheme.value = value
})

const onThemeChange = async () => {
  await setTheme(selectedTheme.value, { persistRemote: true })
}
</script>

<style scoped>
.theme-select {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-surface);
  color: var(--color-text);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.theme-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-focus-ring);
}
</style>
