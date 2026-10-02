function run_platemo_batch(config_path)
%RUN_PLATEMO_BATCH 按 JSON 配置顺序运行 PlatEMO 实验。
%   run_platemo_batch('experiment_config.json')
%
%   每次调用建立独立实验目录，结果仅由 manifest.json 清单引用。
%   结束时打印 BATCH_SUMMARY；有失败则抛错，便于 matlab -batch 返回非零。
    if nargin < 1
        error('Usage: run_platemo_batch(config_path)');
    end
    config_path = resolvePath(char(config_path));
    if ~isfile(config_path)
        error('Config not found: %s', config_path);
    end

    script_dir = fileparts(mfilename('fullpath'));
    platemo_dir = findPlatEMO(script_dir);
    addpath(genpath(platemo_dir));

    cfg = jsondecode(fileread(config_path));
    algorithms = asList(requiredField(cfg, 'algorithms'));
    problems = asList(requiredField(cfg, 'problems'));
    metrics = cellstr(requiredField(cfg, 'metrics'));
    N = double(requiredField(cfg, 'N'));
    maxFE = double(requiredField(cfg, 'maxFE'));
    runs = double(requiredField(cfg, 'runs'));
    saveCount = double(requiredField(cfg, 'save_count'));
    assert(isscalar(N) && isscalar(maxFE) && isscalar(runs) && isscalar(saveCount) && ...
        all(isfinite([N,maxFE,runs,saveCount])) && ...
        all([N,maxFE,runs,saveCount] == fix([N,maxFE,runs,saveCount])) && ...
        N > 0 && maxFE > 0 && runs >= 1 && saveCount > 0, ...
        'N, maxFE, runs, and save_count must be positive (save_count > 0 writes Data/*.mat).');
    assert(~isempty(algorithms) && ~isempty(problems) && ~isempty(metrics), ...
        'algorithms, problems, and metrics must not be empty.');
    % cell 保证单条算法/问题在 JSON 快照中仍是数组。
    for a = 1:numel(algorithms)
        algorithms{a}.params = specParams(algorithms{a});
    end
    for p = 1:numel(problems)
        problems{p}.params = specParams(problems{p});
    end
    cfg.algorithms = algorithms;
    cfg.problems = problems;
    cfg.metrics = metrics;

    labels = cellfun(@algorithmLabel, algorithms, 'UniformOutput', false);
    assert(numel(unique(labels)) == numel(labels), ...
        'Algorithm labels must be unique. Set label for variants of the same class.');
    experiment_id = newExperimentId(cfg);
    experiment_root = fullfile(platemo_dir,'Experiments');
    if isfield(cfg,'experiment_root')
        experiment_root = char(cfg.experiment_root);
        if ~java.io.File(experiment_root).isAbsolute()
            experiment_root = fullfile(fileparts(config_path),experiment_root);
        end
    end
    experiment_dir = fullfile(experiment_root, experiment_id);
    assert(~isfolder(experiment_dir), 'Experiment already exists: %s', experiment_dir);
    [ok,msg] = mkdir(experiment_dir);
    assert(ok, 'Cannot create experiment: %s', msg);
    manifest_path = fullfile(experiment_dir, 'manifest.json');
    manifest = struct('schema_version',1, 'experiment_id',experiment_id, ...
        'created_at',datestr(now,30), 'status','running', 'config',cfg, ...
        'platform_sources',{platformSources(platemo_dir,metrics)}, ...
        'expected_runs',numel(algorithms)*numel(problems)*runs, 'records',{{}});
    writeJson(fullfile(experiment_dir,'config.json'),cfg);
    writeJson(manifest_path,manifest);

    old_dir = cd(platemo_dir);
    guard = onCleanup(@() restoreState(old_dir)); %#ok<NASGU>
    log_path = fullfile(experiment_dir, 'batch_run.log');
    diary(log_path);

    total = numel(algorithms) * numel(problems) * runs;
    count = 0;
    fail = 0;
    t0 = tic;
    fprintf('=== PlatEMO Batch Runner ===\n');
    fprintf('Config: %s\n', config_path);
    fprintf('Algorithms: %d | Problems: %d | Runs: %d | Total: %d\n', ...
        numel(algorithms), numel(problems), runs, total);
    fprintf('N=%g  maxFE=%g  save=%g  Metrics: %s\n', N, maxFE, saveCount, strjoin(metrics, ', '));
    fprintf('EXPERIMENT_ID=%s\nMANIFEST=%s\n', experiment_id, manifest_path);
    fprintf('Results: %s\n\n', experiment_dir);

    for a = 1:numel(algorithms)
        algo = algorithms{a};
        algoArg = callableArg(algo);
        algoName = char(algo.class);
        algoSources = classSources(algoName,platemo_dir,true);
        for p = 1:numel(problems)
            prob = problems{p};
            probArg = callableArg(prob);
            M = double(requiredField(prob, 'M'));
            probSources = classSources(char(prob.class),platemo_dir,false);
            case_dir = fullfile(experiment_dir,'Data',sprintf('a%03d_p%03d',a,p));
            [ok,msg] = mkdir(case_dir);
            assert(ok, 'Cannot create result directory: %s', msg);
            for r = 1:runs
                count = count + 1;
                fprintf('[%d/%d] %s x %s (M=%g) run=%d ... ', ...
                    count, total, algoName, char(prob.class), M, r);
                try
                    info = struct('experiment_id',experiment_id, 'algorithm',algoName, ...
                        'label',labels{a}, 'algorithm_params',{specParams(algo)}, ...
                        'algorithm_sources',{algoSources}, 'problem',char(prob.class), ...
                        'problem_params',{specParams(prob)}, 'problem_sources',{probSources}, ...
                        'problem_index',p, 'run',r, 'requested_N',N, 'maxFE',maxFE);
                    output = @(A,P) saveExperimentResult(A,P,case_dir,info);
                    args = {'algorithm', algoArg, 'problem', probArg, ...
                            'M', M, 'N', N, 'maxFE', maxFE, ...
                            'save', saveCount, 'metName', metrics, 'run', r, 'outputFcn',output};
                    if isfield(prob, 'D') && ~isempty(prob.D) && double(prob.D) > 0
                        args = [args, {'D', double(prob.D)}]; %#ok<AGROW>
                    end
                    platemo(args{:});
                    files = dir(fullfile(case_dir,sprintf('*_%d.mat',r)));
                    assert(numel(files) == 1, 'Expected one saved result for run %d, found %d.',r,numel(files));
                    result_path = fullfile(files(1).folder,files(1).name);
                    saved = load(result_path,'experiment_info');
                    record = saved.experiment_info;
                    record.status = 'ok';
                    record.file = strrep(result_path(length(experiment_dir)+2:end),'\','/');
                    record.sha256 = fileHash(result_path);
                    manifest.records{end+1} = record;
                    fprintf('OK\n');
                catch ME
                    fail = fail + 1;
                    manifest.records{end+1} = struct('algorithm',algoName, 'label',labels{a}, ...
                        'problem',char(prob.class), 'problem_index',p, 'run',r, ...
                        'status','failed', 'error',ME.message);
                    fprintf('FAIL: %s\n', ME.message);
                end
                writeJson(manifest_path,manifest);
            end
        end
    end

    elapsed = toc(t0);
    manifest.status = 'completed';
    if fail > 0
        manifest.status = 'failed';
    end
    manifest.elapsed = elapsed;
    writeJson(manifest_path,manifest);
    fprintf('\nBATCH_SUMMARY ok=%d fail=%d elapsed=%.0f\n', count - fail, fail, elapsed);
    if fail > 0
        error('PlatEMO:BatchFailed', '%d run(s) failed. See %s', fail, log_path);
    end
end

function value = requiredField(s, name)
    if ~isfield(s, name)
        error('Missing config field: %s', name);
    end
    value = s.(name);
end

function items = asList(items)
    % 保留不同条目的可选字段，避免 label/params 不一致时无法拼接 struct。
    if ~iscell(items)
        items = num2cell(items);
    end
end

function label = algorithmLabel(spec)
    label = char(requiredField(spec,'class'));
    if isfield(spec,'label')
        label = char(spec.label);
    end
    assert(~isempty(regexp(label,'^[A-Za-z][A-Za-z0-9_-]*$','once')), ...
        'Invalid algorithm label: %s',label);
end

function values = specParams(spec)
    values = {};
    if isfield(spec,'params')
        values = spec.params;
        if ~iscell(values)
            values = num2cell(values(:)');
        end
    end
end

function id = newExperimentId(cfg)
    token = char(java.util.UUID.randomUUID());
    id = ['exp_' datestr(now,'yyyymmdd_HHMMSS') '_' token(1:8)];
    if isfield(cfg,'experiment_id')
        id = char(cfg.experiment_id);
    end
    assert(~isempty(regexp(id,'^[A-Za-z0-9][A-Za-z0-9_-]*$','once')), ...
        'Invalid experiment_id: %s',id);
end

function saveExperimentResult(Algorithm,Problem,folder,info)
    % 沿用平台的指标计算和 result 结构，仅改变保存位置并补充来源信息。
    if Problem.FE < Problem.maxFE
        return;
    end
    for i = 1:numel(Algorithm.metName)
        Algorithm.CalMetric(Algorithm.metName{i});
    end
    result = Algorithm.result;
    metric = Algorithm.metric;
    experiment_info = info;
    experiment_info.M = Problem.M;
    experiment_info.D = Problem.D;
    experiment_info.actual_N = Problem.N;
    experiment_info.actual_FE = Problem.FE;
    file = fullfile(folder,sprintf('%s_%s_M%d_D%d_%d.mat', ...
        class(Algorithm),class(Problem),Problem.M,Problem.D,Algorithm.run));
    assert(~isfile(file), 'Result already exists: %s',file);
    save(file,'result','metric','experiment_info','-v7');
end

function sources = platformSources(root,metrics)
    paths = {fullfile(root,'platemo.m'),fullfile(root,'Algorithms','ALGORITHM.m'), ...
        fullfile(root,'Problems','PROBLEM.m')};
    for i = 1:numel(metrics)
        path = which(metrics{i});
        assert(~isempty(path), 'Metric not found: %s',metrics{i});
        paths{end+1} = path; %#ok<AGROW>
    end
    sources = sourceRecords(paths,root);
end

function sources = classSources(name,root,includeWeights)
    path = which(name);
    assert(~isempty(path), 'Class not found: %s',name);
    folder = fileparts(path);
    files = [dir(fullfile(folder,'*.m'));dir(fullfile(folder,'*.py'))];
    if includeWeights
        weight_dir = fullfile(folder,'pretrained_weights');
        files = [files;dir(fullfile(weight_dir,'**','*.pth')); ...
            dir(fullfile(weight_dir,'**','*.json'))];
    end
    paths = arrayfun(@(f)fullfile(f.folder,f.name),files,'UniformOutput',false);
    sources = sourceRecords(paths,root);
end

function sources = sourceRecords(paths,root)
    sources = cell(1,numel(paths));
    for i = 1:numel(paths)
        path = paths{i};
        name = strrep(path,'\','/');
        prefix = [strrep(root,'\','/') '/'];
        if startsWith(name,prefix)
            name = name(length(prefix)+1:end);
        end
        sources{i} = struct('path',name,'sha256',fileHash(path));
    end
end

function digest = fileHash(path)
    [fid,msg] = fopen(path,'rb');
    assert(fid >= 0, 'Cannot read %s: %s',path,msg);
    guard = onCleanup(@() fclose(fid)); %#ok<NASGU>
    md = java.security.MessageDigest.getInstance('SHA-256');
    while ~feof(fid)
        md.update(fread(fid,1024*1024,'*uint8'));
    end
    bytes = typecast(md.digest(),'uint8');
    digest = lower(reshape(dec2hex(bytes,2).',1,[]));
end

function writeJson(path,value)
    % 先写临时文件再替换，避免中断时留下半份清单。
    temporary = [path '.tmp'];
    [fid,msg] = fopen(temporary,'w','n','UTF-8');
    assert(fid >= 0, 'Cannot write %s: %s',temporary,msg);
    guard = onCleanup(@() fclose(fid));
    fprintf(fid,'%s\n',jsonencode(value));
    clear guard;
    [ok,msg] = movefile(temporary,path,'f');
    assert(ok, 'Cannot publish %s: %s',path,msg);
end

function arg = callableArg(spec)
    name = char(requiredField(spec, 'class'));
    if isempty(regexp(name, '^[A-Za-z]\w*$', 'once'))
        error('Invalid class name: %s', name);
    end
    fh = str2func(name);
    if isfield(spec, 'params') && ~isempty(spec.params)
        vals = spec.params;
        if iscell(vals)
            extra = vals(:)';
        else
            extra = num2cell(double(vals(:)'));
        end
        arg = [{fh}, extra];
    else
        arg = fh;
    end
end

function platemo_dir = findPlatEMO(script_dir)
    % 技能目录、发行包根目录或 PlatEMO 目录本身都能启动。
    starts = {pwd, script_dir};
    env_root = getenv('PLATEMO_ROOT');
    if ~isempty(env_root)
        starts = [{env_root}, starts];
    end
    for i = 1:numel(starts)
        d = char(starts{i});
        for k = 1:8
            if isfile(fullfile(d, 'platemo.m'))
                platemo_dir = d;
                return;
            end
            nested = fullfile(d, 'PlatEMO', 'platemo.m');
            if isfile(nested)
                platemo_dir = fileparts(nested);
                return;
            end
            parent = fileparts(d);
            if isempty(parent) || strcmp(parent, d)
                break;
            end
            d = parent;
        end
    end
    error('platemo.m not found from %s or %s', pwd, script_dir);
end

function pathOut = resolvePath(pathIn)
    info = dir(pathIn);
    if isempty(info)
        pathOut = pathIn;
        return;
    end
    pathOut = fullfile(info(1).folder, info(1).name);
end

function restoreState(old_dir)
    diary off;
    cd(old_dir);
end
