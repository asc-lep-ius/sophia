<script lang="ts">
  import { resolve } from "$app/paths";
  import { m } from "$lib/paraglide/messages.js";

  const choosePath = resolve("/study", {});
</script>

<!--
  What a course-scoped page says before any course is selected. The picker
  lives on /app/study and nowhere else, so this points there rather than
  offering a second place to choose.
-->
<p class="notice">
  {m.dashboard_no_learning_path()}
  <a href={choosePath}>{m.tenant_course_choose()}</a>
</p>

<style>
  .notice {
    margin: 0;
    overflow-wrap: anywhere;
  }

  a {
    color: var(--accent-strong);
  }
</style>
