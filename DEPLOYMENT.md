# Deployment Guide

## Testing Locally (Before Deploying)

1. **Start a local server:**

   ```bash
   python3 -m http.server 8000
   ```

2. **Test in your browser:**
   - Main site: http://localhost:8000/
   - Demo site: http://localhost:8000/projects/demo/
3. **Verify:**
   - [ ] Navigation menu shows all links including "Demo"
   - [ ] Click "Demo" link → should load the AI Scientist visualization
   - [ ] All pages load correctly
   - [ ] No broken links

## Deploying to GitHub Pages

### One-Time Setup

Verify GitHub Pages is configured (should already be set):

1. Go to: https://github.com/shen-chenyu/shen-chenyu.github.io/settings/pages
2. Confirm settings:
   - **Source**: Deploy from a branch
   - **Branch**: `master` (or `main`)
   - **Folder**: `/ (root)`

### Deploy Changes

```bash
# 1. Add all changes
git add .

# 2. Commit with a descriptive message
git commit -m "Migrate from Gridea, integrate docs demo site"

# 3. Push to GitHub
git push origin master

# 4. Wait 1-2 minutes for GitHub Pages to rebuild

# 5. Visit your site
open https://shen-chenyu.github.io
```

### Verify Deployment

After pushing:

1. **Check main site**: https://shen-chenyu.github.io

   - Verify navigation includes "Demo" link
   - Check footer (should NOT say "Powered by Gridea")

2. **Check demo site**: https://shen-chenyu.github.io/projects/demo/

   - Should show "Autonomous Research Workflow" visualization
   - Interactive tree should load and be scrollable
   - Timelines should display

3. **Check GitHub Pages status**:
   - Go to: https://github.com/shen-chenyu/shen-chenyu.github.io/deployments
   - Look for latest deployment (should show "Active")

## Troubleshooting

### Demo site shows 404

- Check that `/projects/demo/` folder exists in your repository
- Verify `projects/demo/index.html` exists
- Clear browser cache and try again

### Changes not appearing

- Wait 2-3 minutes (GitHub Pages needs time to rebuild)
- Check GitHub Actions: https://github.com/shen-chenyu/shen-chenyu.github.io/actions
- Force refresh browser: Cmd+Shift+R (Mac) or Ctrl+Shift+R (Windows)

### Demo site links broken

- Ensure demo site uses relative paths (should already be set)
- Links in docs should start with `assets/` not `/assets/`

## Future Updates

### Update main blog content

1. Edit HTML files in `/post/`, `/archives/`, etc.
2. Test locally with `python3 -m http.server 8000`
3. Deploy: `git add . && git commit -m "msg" && git push`

### Update demo site

1. Edit files in `/projects/demo/`
2. Test locally: `python3 -m http.server 8000` → http://localhost:8000/projects/demo/
3. Deploy: `git add . && git commit -m "msg" && git push`

## Quick Commands Cheat Sheet

```bash
# Preview locally
python3 -m http.server 8000

# Deploy changes
git add .
git commit -m "Your update message"
git push origin master

# Check what changed
git status
git diff

# View deployment status
open https://github.com/shen-chenyu/shen-chenyu.github.io/deployments
```
