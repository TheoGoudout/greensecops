// Close a pull request that touches the dependency files unless its author is
// an organization member or an allowed bot.
//
// Loaded by actions/github-script, which supplies github, context and core.
module.exports = async ({ github, context, core }) => {
  const pr = context.payload.pull_request;
  const author = pr.user.login;
  const assoc = pr.author_association;

  const botAllowlist = new Set(['dependabot[bot]']);
  const orgAuthorAssociations = new Set(['MEMBER', 'OWNER']);

  const allowed =
    botAllowlist.has(author) ||
    (assoc != null && orgAuthorAssociations.has(assoc));

  if (!allowed) {
    await github.rest.issues.createComment({
      owner: context.repo.owner,
      repo: context.repo.repo,
      issue_number: context.payload.pull_request.number,
      body: `This PR modifies dependency files (\`pyproject.toml\` or \`uv.lock\`), which is restricted to members of the **${context.repo.owner}** organization on GitHub.\n\nIf you need a dependency change, please [open a discussion](https://github.com/${context.repo.owner}/${context.repo.repo}/discussions/new) describing what you need and why.\n\nClosing this PR automatically.`
    });

    await github.rest.pulls.update({
      owner: context.repo.owner,
      repo: context.repo.repo,
      pull_number: context.payload.pull_request.number,
      state: 'closed'
    });

    core.setFailed('Dependency changes are restricted to organization members.');
  } else {
    console.log(`Author ${author} (author_association=${assoc}) is allowed to make dependency changes.`);
  }
};
