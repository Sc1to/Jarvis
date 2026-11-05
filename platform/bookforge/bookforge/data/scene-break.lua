-- A scene break in the manuscript is a Markdown rule (`* * *`). Each format shows it as centred asterisks
-- rather than a ruled line.
function HorizontalRule()
  local f = FORMAT or ''
  if f:match('docx') then
    return pandoc.Div({ pandoc.Para({ pandoc.Str('* * *') }) }, pandoc.Attr('', {}, { { 'custom-style', 'SceneBreak' } }))
  elseif f:match('epub') or f:match('html') then
    return pandoc.RawBlock('html', '<p class="scene-break">* * *</p>')
  elseif f:match('latex') then
    return pandoc.RawBlock('latex', '\\begin{center}\\vspace{0.6em}* * *\\vspace{0.6em}\\end{center}')
  elseif f:match('typst') then
    return pandoc.RawBlock('typst', '#align(center)[#v(0.6em)\\* \\* \\*#v(0.6em)]')
  end
end
